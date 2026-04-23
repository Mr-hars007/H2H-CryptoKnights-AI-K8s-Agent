from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
KUSTOMIZE_DIR = REPO_ROOT / "k8s" / "manifests"
NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
KUBECTL_BIN = os.getenv("AI_KUBECTL_BIN", "kubectl")


def run(cmd: List[str], timeout: int = 15) -> str:
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if not stdout and stderr:
            return f"Error: {stderr}"
        return stdout if stdout else "No output"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as exc:
        return f"Error: {str(exc)}"


def initialize_cluster() -> str:
    if KUSTOMIZE_DIR.exists():
        return run([KUBECTL_BIN, "apply", "-k", str(KUSTOMIZE_DIR)], timeout=30)
    return run([KUBECTL_BIN, "create", "namespace", NAMESPACE])


def delete_all() -> str:
    return run([KUBECTL_BIN, "delete", "namespace", NAMESPACE, "--ignore-not-found=true"], timeout=30)


def revert() -> str:
    first = delete_all()
    second = initialize_cluster()
    return f"{first}\n{second}".strip()


def get_pod_status() -> List[Dict[str, object]]:
    try:
        result = subprocess.run(
            [KUBECTL_BIN, "get", "pods", "-n", NAMESPACE, "-o", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except Exception:
        return []

    pods: List[Dict[str, object]] = []
    for item in data.get("items", []):
        metadata = item.get("metadata", {}) or {}
        status_obj = item.get("status", {}) or {}
        name = str(metadata.get("name", ""))
        status = str(status_obj.get("phase", "Unknown"))
        restarts = 0

        container_statuses = status_obj.get("containerStatuses", []) or []
        if container_statuses:
            first = container_statuses[0] or {}
            try:
                restarts = int(first.get("restartCount", 0) or 0)
            except Exception:
                restarts = 0

            state = first.get("state", {}) or {}
            waiting = state.get("waiting")
            terminated = state.get("terminated")

            if isinstance(waiting, dict) and waiting.get("reason"):
                status = str(waiting["reason"])
            elif isinstance(terminated, dict) and terminated.get("reason"):
                status = str(terminated["reason"])

        pods.append(
            {
                "name": name,
                "status": status,
                "restarts": restarts,
            }
        )

    return sorted(pods, key=lambda x: str(x["name"]))


def create_pod(name: str = "test-pod") -> str:
    return run([KUBECTL_BIN, "run", name, "--image=nginx", "-n", NAMESPACE, "--restart=Never"])


def delete_pod(name: str) -> str:
    return run([KUBECTL_BIN, "delete", "pod", name, "-n", NAMESPACE, "--ignore-not-found=true"])


def pause_deployment(name: str) -> str:
    return run([KUBECTL_BIN, "scale", "deployment", name, "--replicas=0", "-n", NAMESPACE])


def start_deployment(name: str, replicas: int = 1) -> str:
    return run([KUBECTL_BIN, "scale", "deployment", name, f"--replicas={replicas}", "-n", NAMESPACE])


def crashloop_orders() -> str:
    patch = json.dumps(
        [
            {
                "op": "add",
                "path": "/spec/template/spec/containers/0/command",
                "value": ["sh", "-c", "exit 1"],
            }
        ]
    )
    return run([KUBECTL_BIN, "patch", "deployment", "orders", "-n", NAMESPACE, "--type=json", "-p", patch])


def pending_payments() -> str:
    patch = json.dumps(
        {
            "spec": {
                "template": {
                    "spec": {
                        "nodeSelector": {
                            "ai-k8s": "pending"
                        }
                    }
                }
            }
        }
    )
    return run([KUBECTL_BIN, "patch", "deployment", "payments", "-n", NAMESPACE, "-p", patch])


def misconfigure_service() -> str:
    patch = json.dumps(
        {
            "spec": {
                "selector": {
                    "app": "wrong-selector"
                }
            }
        }
    )
    return run([KUBECTL_BIN, "patch", "service", "gateway", "-n", NAMESPACE, "-p", patch])