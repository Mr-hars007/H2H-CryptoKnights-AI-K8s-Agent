"""Phase 4 observability tools for evidence collection and cluster monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import time
import subprocess
from typing import Dict, List, Optional


def _env_list(name: str, fallback: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return fallback
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    return parsed or fallback


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
DEFAULT_SERVICES = _env_list("AI_K8S_SERVICES", ["gateway", "orders", "payments"])
KUBECTL_BIN = os.getenv("AI_KUBECTL_BIN", "kubectl")
MAX_STEP_STDOUT_CHARS = int(os.getenv("AI_EVIDENCE_MAX_STEP_STDOUT_CHARS", "2400"))
LOG_SIGNAL_LINES = int(os.getenv("AI_EVIDENCE_LOG_SIGNAL_LINES", "30"))
LOG_TAIL_FALLBACK_LINES = int(os.getenv("AI_EVIDENCE_LOG_TAIL_FALLBACK_LINES", "12"))

SIGNAL_TOKENS = [
    "error",
    "exception",
    "fail",
    "failed",
    "warning",
    "timeout",
    "refused",
    "unhealthy",
    "backoff",
    "crash",
    "oom",
    "killed",
    "panic",
    "denied",
    "not found",
]


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kubectl(command: List[str], namespace: str | None = None) -> List[str]:
    cmd = [KUBECTL_BIN]
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(command)
    return cmd


def _run_command(command: List[str]) -> Dict[str, str | int | bool]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "command": " ".join(command),
        }
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": " ".join(command),
    }


def _extract_signal_lines(text: str, max_lines: int = LOG_SIGNAL_LINES) -> List[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    matched: List[str] = []
    for line in lines:
        lowered = line.lower()
        if any(token in lowered for token in SIGNAL_TOKENS):
            matched.append(line)
            if len(matched) >= max_lines:
                break

    if not matched:
        return lines[-min(LOG_TAIL_FALLBACK_LINES, len(lines)):]

    return matched


def _compress_step_output(step: Dict[str, str | int | bool]) -> Dict[str, object]:
    compressed = dict(step)
    command = str(compressed.get("command", ""))
    stdout = str(compressed.get("stdout", "") or "")
    stderr = str(compressed.get("stderr", "") or "")

    signal_lines: List[str] = []
    if " logs " in command or command.endswith(" logs"):
        signal_lines = _extract_signal_lines(stdout, max_lines=LOG_SIGNAL_LINES)
    elif " describe " in command or " get events" in command:
        signal_lines = _extract_signal_lines(stdout, max_lines=min(20, LOG_SIGNAL_LINES))

    if signal_lines:
        compressed["signal_lines"] = signal_lines

    if len(stdout) > MAX_STEP_STDOUT_CHARS:
        compressed["stdout"] = stdout[:MAX_STEP_STDOUT_CHARS]
        compressed["stdout_truncated"] = True
        compressed["stdout_original_length"] = len(stdout)

    if len(stderr) > MAX_STEP_STDOUT_CHARS:
        compressed["stderr"] = stderr[:MAX_STEP_STDOUT_CHARS]
        compressed["stderr_truncated"] = True
        compressed["stderr_original_length"] = len(stderr)

    if signal_lines:
        compressed["summary"] = {
            "signal_line_count": len(signal_lines),
            "has_error_signal": any("error" in line.lower() or "fail" in line.lower() for line in signal_lines),
        }

    return compressed


def _run_command_compact(command: List[str]) -> Dict[str, object]:
    return _compress_step_output(_run_command(command))


def _list_service_pods(namespace: str, app_name: str) -> List[str]:
    selector_result = _run_command(_kubectl(["get", "service", app_name, "-o", "json"], namespace=namespace))
    if not selector_result["ok"]:
        return []

    try:
        selector_payload = json.loads(str(selector_result["stdout"]) or "{}")
    except json.JSONDecodeError:
        return []

    selector = selector_payload.get("spec", {}).get("selector") or {}
    if not selector:
        return []

    label_selector = ",".join(f"{k}={v}" for k, v in selector.items())
    if not label_selector:
        return []

    pods_result = _run_command(
        _kubectl(
            ["get", "pods", "-l", label_selector, "-o", "jsonpath={.items[*].metadata.name}"],
            namespace=namespace,
        )
    )
    if not pods_result["ok"]:
        return []
    stdout = str(pods_result["stdout"]).strip()
    if not stdout:
        return []
    return stdout.split()


def discover_services(namespace: str = DEFAULT_NAMESPACE, require_selector: bool = True) -> Dict[str, object]:
    result = _run_command(_kubectl(["get", "svc", "-o", "json"], namespace=namespace))
    if not result["ok"]:
        return {
            "ok": False,
            "namespace": namespace,
            "services": [],
            "error": str(result.get("stderr") or result.get("stdout") or "Failed to list services"),
            "step": result,
        }

    try:
        payload = json.loads(str(result["stdout"]) or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "namespace": namespace,
            "services": [],
            "error": f"Unable to parse service list: {exc}",
            "step": result,
        }

    discovered = []
    skipped = []

    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})

        name = str(metadata.get("name", "")).strip()
        if not name or name == "kubernetes":
            continue

        selector = spec.get("selector") or {}
        if require_selector and not selector:
            skipped.append({"service": name, "reason": "no_selector"})
            continue

        discovered.append(name)

    return {
        "ok": True,
        "namespace": namespace,
        "services": discovered,
        "skipped": skipped,
        "source": "live_cluster",
        "captured_at": _utc_timestamp(),
    }


def collect_evidence_snapshot(
    namespace: str = DEFAULT_NAMESPACE,
    services: Optional[List[str]] = None,
    log_tail_lines: int = 120,
    include_describe: bool = True,
) -> Dict[str, object]:
    service_discovery = discover_services(namespace=namespace, require_selector=True)
    if services:
        target_services = services
    elif service_discovery.get("ok") and service_discovery.get("services"):
        target_services = list(service_discovery.get("services", []))
    else:
        target_services = DEFAULT_SERVICES

    cluster_overview = [
        _run_command_compact(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace)),
        _run_command_compact(_kubectl(["get", "svc", "-o", "wide"], namespace=namespace)),
        _run_command_compact(_kubectl(["get", "deploy", "-o", "wide"], namespace=namespace)),
        _run_command_compact(_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace=namespace)),
    ]

    services_evidence: Dict[str, object] = {}
    for service in target_services:
        service_steps: List[Dict[str, object]] = [
            _run_command_compact(_kubectl(["get", "deployment", service, "-o", "wide"], namespace=namespace)),
            _run_command_compact(_kubectl(["get", "service", service, "-o", "wide"], namespace=namespace)),
        ]

        if include_describe:
            service_steps.extend(
                [
                    _run_command_compact(_kubectl(["describe", "deployment", service], namespace=namespace)),
                    _run_command_compact(_kubectl(["describe", "service", service], namespace=namespace)),
                ]
            )

        pod_evidence: Dict[str, object] = {}
        for pod in _list_service_pods(namespace=namespace, app_name=service):
            pod_steps = [
                _run_command_compact(_kubectl(["get", "pod", pod, "-o", "wide"], namespace=namespace)),
                _run_command_compact(
                    _kubectl(
                        ["logs", pod, "--tail", str(log_tail_lines), "--since=1h", "--timestamps"],
                        namespace=namespace,
                    )
                ),
            ]

            if include_describe:
                pod_steps.append(_run_command_compact(_kubectl(["describe", "pod", pod], namespace=namespace)))

            pod_evidence[pod] = {
                "ok": all(step["ok"] for step in pod_steps),
                "steps": pod_steps,
            }

        services_evidence[service] = {
            "ok": all(step["ok"] for step in service_steps),
            "pods": pod_evidence,
            "steps": service_steps,
        }

    return {
        "ok": all(step["ok"] for step in cluster_overview)
        and all(bool(v.get("ok")) for v in services_evidence.values()),
        "phase": "phase4_observability",
        "kind": "evidence_snapshot",
        "captured_at": _utc_timestamp(),
        "namespace": namespace,
        "services": target_services,
        "service_discovery": service_discovery,
        "cluster_overview": cluster_overview,
        "service_evidence": services_evidence,
    }


def _lightweight_health_check(namespace: str) -> Dict[str, object]:
    steps = [
        _run_command_compact(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace)),
        _run_command_compact(_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace=namespace)),
    ]
    return {
        "ok": all(step["ok"] for step in steps),
        "captured_at": _utc_timestamp(),
        "steps": steps,
    }


def monitor_cluster_health(
    namespace: str = DEFAULT_NAMESPACE,
    samples: int = 3,
    interval_seconds: int = 10,
) -> Dict[str, object]:
    safe_samples = max(1, samples)
    safe_interval = max(1, interval_seconds)

    observations = []
    for i in range(safe_samples):
        observations.append(_lightweight_health_check(namespace=namespace))
        if i != safe_samples - 1:
            time.sleep(safe_interval)

    return {
        "ok": all(observation["ok"] for observation in observations),
        "phase": "phase4_observability",
        "kind": "health_monitor",
        "captured_at": _utc_timestamp(),
        "namespace": namespace,
        "samples": safe_samples,
        "interval_seconds": safe_interval,
        "observations": observations,
    }
