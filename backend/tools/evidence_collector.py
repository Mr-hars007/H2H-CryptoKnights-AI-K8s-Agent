"""Phase 4 observability tools for evidence collection and cluster monitoring."""

from __future__ import annotations

from datetime import datetime, timezone
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


def _list_service_pods(namespace: str, app_name: str) -> List[str]:
    pods_result = _run_command(
        _kubectl(
            ["get", "pods", "-l", f"app={app_name}", "-o", "jsonpath={.items[*].metadata.name}"],
            namespace=namespace,
        )
    )
    if not pods_result["ok"]:
        return []
    stdout = str(pods_result["stdout"]).strip()
    if not stdout:
        return []
    return stdout.split()


def collect_evidence_snapshot(
    namespace: str = DEFAULT_NAMESPACE,
    services: Optional[List[str]] = None,
    log_tail_lines: int = 120,
    include_describe: bool = True,
) -> Dict[str, object]:
    target_services = services or DEFAULT_SERVICES

    cluster_overview = [
        _run_command(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace)),
        _run_command(_kubectl(["get", "svc", "-o", "wide"], namespace=namespace)),
        _run_command(_kubectl(["get", "deploy", "-o", "wide"], namespace=namespace)),
        _run_command(_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace=namespace)),
    ]

    services_evidence: Dict[str, object] = {}
    for service in target_services:
        service_steps: List[Dict[str, str | int | bool]] = [
            _run_command(_kubectl(["get", "deployment", service, "-o", "wide"], namespace=namespace)),
            _run_command(_kubectl(["get", "service", service, "-o", "wide"], namespace=namespace)),
        ]

        if include_describe:
            service_steps.extend(
                [
                    _run_command(_kubectl(["describe", "deployment", service], namespace=namespace)),
                    _run_command(_kubectl(["describe", "service", service], namespace=namespace)),
                ]
            )

        pod_evidence: Dict[str, object] = {}
        for pod in _list_service_pods(namespace=namespace, app_name=service):
            pod_steps = [
                _run_command(_kubectl(["get", "pod", pod, "-o", "wide"], namespace=namespace)),
                _run_command(
                    _kubectl(
                        ["logs", pod, "--tail", str(log_tail_lines), "--timestamps"],
                        namespace=namespace,
                    )
                ),
            ]

            if include_describe:
                pod_steps.append(_run_command(_kubectl(["describe", "pod", pod], namespace=namespace)))

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
        "cluster_overview": cluster_overview,
        "service_evidence": services_evidence,
    }


def _lightweight_health_check(namespace: str) -> Dict[str, object]:
    steps = [
        _run_command(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace)),
        _run_command(_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace=namespace)),
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
