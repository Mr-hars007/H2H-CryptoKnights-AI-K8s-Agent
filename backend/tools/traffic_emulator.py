"""Generate real in-cluster traffic against live Kubernetes Services."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import subprocess
import time
from typing import Dict, List, Optional


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
KUBECTL_BIN = os.getenv("AI_KUBECTL_BIN", "kubectl")
DEFAULT_REQUESTS_PER_SERVICE = int(os.getenv("AI_TRAFFIC_REQUESTS_PER_SERVICE", "20"))
DEFAULT_INTERVAL_SECONDS = int(os.getenv("AI_TRAFFIC_INTERVAL_SECONDS", "1"))
DEFAULT_REQUEST_TIMEOUT_SECONDS = int(os.getenv("AI_TRAFFIC_REQUEST_TIMEOUT_SECONDS", "2"))
TRAFFIC_IMAGE = os.getenv("AI_TRAFFIC_IMAGE", "curlimages/curl:8.7.1")


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


def _service_has_endpoints(namespace: str, service_name: str) -> bool:
    result = _run_command(
        _kubectl(
            [
                "get",
                "endpoints",
                service_name,
                "-o",
                "jsonpath={.subsets[*].addresses[*].ip}",
            ],
            namespace=namespace,
        )
    )
    if not result["ok"]:
        return False
    return bool(str(result["stdout"]).strip())


def discover_service_targets(
    namespace: str = DEFAULT_NAMESPACE,
    services: Optional[List[str]] = None,
    require_endpoints: bool = True,
) -> Dict[str, object]:
    requested = {item.strip() for item in services or [] if item.strip()}
    svc_result = _run_command(_kubectl(["get", "svc", "-o", "json"], namespace=namespace))
    if not svc_result["ok"]:
        return {
            "ok": False,
            "namespace": namespace,
            "services": [],
            "targets": [],
            "error": str(svc_result.get("stderr") or svc_result.get("stdout") or "Failed to list services"),
            "step": svc_result,
        }

    try:
        payload = json.loads(str(svc_result["stdout"]) or "{}")
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "namespace": namespace,
            "services": [],
            "targets": [],
            "error": f"Unable to parse kubectl service JSON: {exc}",
            "step": svc_result,
        }

    targets: List[Dict[str, object]] = []
    skipped: List[Dict[str, str]] = []

    for item in payload.get("items", []):
        metadata = item.get("metadata", {})
        spec = item.get("spec", {})
        name = str(metadata.get("name", "")).strip()
        if not name or name == "kubernetes":
            continue
        if requested and name not in requested:
            continue

        ports = spec.get("ports", []) or []
        tcp_port = None
        for port in ports:
            protocol = str(port.get("protocol", "TCP")).upper()
            if protocol == "TCP" and port.get("port") is not None:
                tcp_port = int(port["port"])
                break

        if tcp_port is None:
            skipped.append({"service": name, "reason": "no_tcp_port"})
            continue

        has_endpoints = _service_has_endpoints(namespace=namespace, service_name=name)
        if require_endpoints and not has_endpoints:
            skipped.append({"service": name, "reason": "no_ready_endpoints"})
            continue

        targets.append(
            {
                "service": name,
                "port": tcp_port,
                "url": f"http://{name}.{namespace}.svc.cluster.local:{tcp_port}",
                "has_endpoints": has_endpoints,
            }
        )

    return {
        "ok": True,
        "namespace": namespace,
        "services": [entry["service"] for entry in targets],
        "targets": targets,
        "requested_services": sorted(requested),
        "skipped": skipped,
        "captured_at": _utc_timestamp(),
    }


def _wait_for_pod_completion(namespace: str, pod_name: str, timeout_seconds: int) -> Dict[str, object]:
    deadline = time.time() + max(10, timeout_seconds)
    phases_seen: List[str] = []

    while time.time() < deadline:
        phase_result = _run_command(
            _kubectl(["get", "pod", pod_name, "-o", "jsonpath={.status.phase}"], namespace=namespace)
        )
        if not phase_result["ok"]:
            return {
                "ok": False,
                "phase": "Unknown",
                "phases_seen": phases_seen,
                "step": phase_result,
            }

        phase = str(phase_result["stdout"] or "Unknown").strip() or "Unknown"
        phases_seen.append(phase)
        if phase in {"Succeeded", "Failed"}:
            return {
                "ok": True,
                "phase": phase,
                "phases_seen": phases_seen,
            }

        time.sleep(2)

    return {
        "ok": False,
        "phase": "Timeout",
        "phases_seen": phases_seen,
    }


def _parse_traffic_logs(log_output: str) -> Dict[str, object]:
    status_counts: Dict[str, int] = {}
    service_counts: Dict[str, int] = {}
    records = 0

    for raw_line in log_output.splitlines():
        line = raw_line.strip()
        if not line.startswith("traffic_event "):
            continue

        records += 1
        fields = {}
        for token in line.split()[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[key] = value

        status = fields.get("status", "unknown")
        service = fields.get("service", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        service_counts[service] = service_counts.get(service, 0) + 1

    success_count = sum(count for status, count in status_counts.items() if status.startswith("2"))
    success_rate = (success_count / records) if records else 0.0

    return {
        "records": records,
        "status_counts": status_counts,
        "service_counts": service_counts,
        "success_count": success_count,
        "success_rate": round(success_rate, 4),
    }


def _parse_probe_logs(log_output: str) -> Dict[str, object]:
    records: List[Dict[str, object]] = []

    for raw_line in log_output.splitlines():
        line = raw_line.strip()
        if not line.startswith("probe_event "):
            continue

        fields: Dict[str, str] = {}
        for token in line.split()[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            fields[key] = value

        latency_ms = 0.0
        try:
            latency_ms = float(fields.get("latency_ms", "0") or 0)
        except ValueError:
            latency_ms = 0.0

        status = str(fields.get("status", "000"))
        error = status.startswith("4") or status.startswith("5") or status in {"000", "timeout", "error"}
        records.append(
            {
                "service": fields.get("service", "unknown"),
                "status": status,
                "latency_ms": round(latency_ms, 2),
                "bytes": int(float(fields.get("bytes", "0") or 0)),
                "error": error,
            }
        )

    total_requests = len(records)
    error_count = sum(1 for record in records if record["error"])
    latency_values = [float(record["latency_ms"]) for record in records if float(record["latency_ms"]) > 0]
    avg_latency_ms = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0.0
    p95_latency_ms = 0.0
    if latency_values:
        sorted_latencies = sorted(latency_values)
        p95_index = max(0, min(len(sorted_latencies) - 1, int(round(0.95 * (len(sorted_latencies) - 1)))))
        p95_latency_ms = round(sorted_latencies[p95_index], 2)

    return {
        "requests": total_requests,
        "errors": error_count,
        "error_rate": round((error_count / total_requests), 4) if total_requests else 0.0,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "records": records,
    }


def run_traffic_emulator(
    namespace: str = DEFAULT_NAMESPACE,
    services: Optional[List[str]] = None,
    requests_per_service: int = DEFAULT_REQUESTS_PER_SERVICE,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    request_timeout_seconds: int = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    keep_pod: bool = False,
) -> Dict[str, object]:
    safe_requests = max(1, requests_per_service)
    safe_interval = max(0, interval_seconds)
    safe_timeout = max(1, request_timeout_seconds)

    discovery = discover_service_targets(namespace=namespace, services=services, require_endpoints=True)
    if not discovery.get("ok"):
        return {
            "ok": False,
            "namespace": namespace,
            "error": discovery.get("error", "Service discovery failed"),
            "discovery": discovery,
        }

    targets = discovery.get("targets", [])
    if not targets:
        return {
            "ok": False,
            "namespace": namespace,
            "error": "No routable services with ready endpoints were discovered.",
            "discovery": discovery,
        }

    pod_name = f"traffic-emulator-{int(time.time())}"
    script_lines = [
        "set -eu",
        f"REQUESTS={safe_requests}",
        f"INTERVAL={safe_interval}",
        f"TIMEOUT={safe_timeout}",
        f"echo traffic_emulator_start ts={_utc_timestamp()} pod={pod_name}",
        "for i in $(seq 1 \"$REQUESTS\"); do",
    ]

    for target in targets:
        service = str(target["service"])
        url = str(target["url"])
        script_lines.extend(
            [
                f"  HTTP_CODE=$(curl -sS -o /tmp/resp.txt -w \"%{{http_code}}\" --max-time \"$TIMEOUT\" \"{url}\" || echo 000)",
                "  BYTES=$(wc -c < /tmp/resp.txt 2>/dev/null || echo 0)",
                "  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)",
                f"  echo traffic_event ts=$TS service={service} attempt=$i status=$HTTP_CODE bytes=$BYTES url={url}",
            ]
        )

    script_lines.extend(
        [
            "  if [ \"$INTERVAL\" -gt 0 ] && [ \"$i\" -lt \"$REQUESTS\" ]; then sleep \"$INTERVAL\"; fi",
            "done",
            f"echo traffic_emulator_end ts={_utc_timestamp()} pod={pod_name}",
        ]
    )
    script = "\n".join(script_lines)

    create_result = _run_command(
        _kubectl(
            [
                "run",
                pod_name,
                "--image",
                TRAFFIC_IMAGE,
                "--restart=Never",
                "--labels",
                "app=ai-traffic-emulator",
                "--command",
                "--",
                "sh",
                "-c",
                script,
            ],
            namespace=namespace,
        )
    )
    if not create_result["ok"]:
        return {
            "ok": False,
            "namespace": namespace,
            "error": "Failed to start traffic emulator pod.",
            "step": create_result,
            "discovery": discovery,
        }

    wait_result = _wait_for_pod_completion(
        namespace=namespace,
        pod_name=pod_name,
        timeout_seconds=(safe_requests * max(1, safe_interval + safe_timeout)) + 60,
    )

    logs_result = _run_command(_kubectl(["logs", pod_name], namespace=namespace))
    cleanup_result = None
    if not keep_pod:
        cleanup_result = _run_command(
            _kubectl(["delete", "pod", pod_name, "--ignore-not-found=true"], namespace=namespace)
        )

    parsed_logs = _parse_traffic_logs(str(logs_result.get("stdout", ""))) if logs_result["ok"] else {}
    pod_phase = str(wait_result.get("phase", "Unknown"))

    return {
        "ok": bool(wait_result.get("ok")) and pod_phase == "Succeeded" and bool(logs_result.get("ok")),
        "phase": "traffic_emulation",
        "kind": "live_cluster_traffic",
        "captured_at": _utc_timestamp(),
        "namespace": namespace,
        "pod_name": pod_name,
        "traffic_targets": discovery.get("targets", []),
        "request_config": {
            "requests_per_service": safe_requests,
            "interval_seconds": safe_interval,
            "request_timeout_seconds": safe_timeout,
        },
        "pod_phase": pod_phase,
        "traffic_summary": parsed_logs,
        "logs": str(logs_result.get("stdout", "")),
        "steps": {
            "create": create_result,
            "wait": wait_result,
            "logs": logs_result,
            "cleanup": cleanup_result,
        },
        "discovery": discovery,
    }


def collect_live_service_stats(
    namespace: str = DEFAULT_NAMESPACE,
    services: Optional[List[str]] = None,
    keep_pod: bool = False,
) -> Dict[str, object]:
    discovery = discover_service_targets(namespace=namespace, services=services, require_endpoints=True)
    if not discovery.get("ok"):
        return {
            "ok": False,
            "namespace": namespace,
            "error": discovery.get("error", "Service discovery failed"),
            "discovery": discovery,
        }

    targets = discovery.get("targets", [])
    if not targets:
        return {
            "ok": False,
            "namespace": namespace,
            "error": "No routable services with ready endpoints were discovered.",
            "discovery": discovery,
        }

    pod_name = f"stats-probe-{int(time.time())}"
    script_lines = [
        "set -eu",
        f"echo probe_start ts={_utc_timestamp()} pod={pod_name}",
    ]

    for target in targets:
        service = str(target["service"])
        url = str(target["url"])
        script_lines.extend(
            [
                f"  START=$(date +%s%3N)",
                f"  HTTP_CODE=$(curl -sS -o /tmp/probe.txt -w \"%{{http_code}}\" --max-time 5 \"{url}\" || echo 000)",
                f"  END=$(date +%s%3N)",
                "  BYTES=$(wc -c < /tmp/probe.txt 2>/dev/null || echo 0)",
                "  LATENCY_MS=$((END-START))",
                "  TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)",
                f"  echo probe_event ts=$TS service={service} status=$HTTP_CODE latency_ms=$LATENCY_MS bytes=$BYTES url={url}",
            ]
        )

    script_lines.append(f"echo probe_end ts={_utc_timestamp()} pod={pod_name}")
    script = "\n".join(script_lines)

    create_result = _run_command(
        _kubectl(
            [
                "run",
                pod_name,
                "--image",
                TRAFFIC_IMAGE,
                "--restart=Never",
                "--labels",
                "app=ai-stats-probe",
                "--command",
                "--",
                "sh",
                "-c",
                script,
            ],
            namespace=namespace,
        )
    )
    if not create_result["ok"]:
        return {
            "ok": False,
            "namespace": namespace,
            "error": "Failed to start stats probe pod.",
            "step": create_result,
            "discovery": discovery,
        }

    wait_result = _wait_for_pod_completion(namespace=namespace, pod_name=pod_name, timeout_seconds=90)
    logs_result = _run_command(_kubectl(["logs", pod_name], namespace=namespace))
    cleanup_result = None
    if not keep_pod:
        cleanup_result = _run_command(_kubectl(["delete", "pod", pod_name, "--ignore-not-found=true"], namespace=namespace))

    probe_summary = _parse_probe_logs(str(logs_result.get("stdout", ""))) if logs_result["ok"] else {}
    traffic_rps = 0.0
    if probe_summary.get("requests"):
        traffic_rps = round(float(probe_summary["requests"]) / max(1.0, float(len(targets))), 2)

    return {
        "ok": bool(wait_result.get("ok")) and bool(logs_result.get("ok")),
        "phase": "live_service_stats",
        "kind": "live_service_stats",
        "captured_at": _utc_timestamp(),
        "namespace": namespace,
        "services": discovery.get("services", []),
        "targets": targets,
        "stats": {
            "requests": probe_summary.get("requests", 0),
            "errors": probe_summary.get("errors", 0),
            "error_rate": probe_summary.get("error_rate", 0.0),
            "avg_latency_ms": probe_summary.get("avg_latency_ms", 0.0),
            "p95_latency_ms": probe_summary.get("p95_latency_ms", 0.0),
            "traffic_rps": traffic_rps,
        },
        "probe_records": probe_summary.get("records", []),
        "logs": str(logs_result.get("stdout", "")),
        "steps": {
            "create": create_result,
            "wait": wait_result,
            "logs": logs_result,
            "cleanup": cleanup_result,
        },
        "discovery": discovery,
    }
