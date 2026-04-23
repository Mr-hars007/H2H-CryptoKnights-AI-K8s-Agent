"""Bootstrap helpers for starting a local Kubernetes demo environment."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import json
import os
import subprocess
import time
from typing import Dict, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
KUSTOMIZE_DIR = REPO_ROOT / "k8s" / "manifests"
NAMESPACE_MANIFEST = REPO_ROOT / "k8s" / "manifests" / "namespace.yaml"
DEFAULT_CLUSTER_NAME = os.getenv("AI_KIND_CLUSTER_NAME", "h2h-lite")
DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
KUBECTL_BIN = os.getenv("AI_KUBECTL_BIN", "kubectl")
KIND_BIN = os.getenv("AI_KIND_BIN", "kind")


@dataclass(frozen=True)
class BootstrapStep:
    name: str
    ok: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


def _run_command(command: List[str]) -> BootstrapStep:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        return BootstrapStep(
            name=command[0],
            ok=False,
            command=" ".join(command),
            stderr=str(exc),
            returncode=127,
        )

    return BootstrapStep(
        name=command[0],
        ok=completed.returncode == 0,
        command=" ".join(command),
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
        returncode=completed.returncode,
    )


def _kind_cluster_exists(cluster_name: str) -> bool:
    step = _run_command([KIND_BIN, "get", "clusters"])
    if not step.ok:
        return False
    clusters = {line.strip() for line in step.stdout.splitlines() if line.strip()}
    return cluster_name in clusters


def _kubectl(command: List[str], context: Optional[str] = None) -> List[str]:
    cmd = [KUBECTL_BIN]
    if context:
        cmd.extend(["--context", context])
    cmd.extend(command)
    return cmd


def _wait_for_ready(context: str, timeout_seconds: int = 180) -> BootstrapStep:
    deadline = time.time() + max(30, timeout_seconds)
    last_step = BootstrapStep(name="kubectl", ok=False, command="wait", returncode=1)

    while time.time() < deadline:
        last_step = _run_command(_kubectl(["get", "nodes", "-o", "json"], context=context))
        if last_step.ok and "Ready" in last_step.stdout:
            return BootstrapStep(
                name="kubectl",
                ok=True,
                command=last_step.command,
                stdout=last_step.stdout,
                stderr=last_step.stderr,
                returncode=last_step.returncode,
            )
        time.sleep(3)

    return BootstrapStep(
        name="kubectl",
        ok=False,
        command=last_step.command,
        stdout=last_step.stdout,
        stderr=last_step.stderr or "Timed out waiting for cluster readiness",
        returncode=last_step.returncode,
    )


def bootstrap_local_cluster(
    cluster_name: str = DEFAULT_CLUSTER_NAME,
    namespace: str = DEFAULT_NAMESPACE,
    create_if_missing: bool = True,
    warmup_traffic: bool = False,
    warmup_requests_per_service: int = 1,
    warmup_interval_seconds: int = 0,
    warmup_timeout_seconds: int = 2,
) -> Dict[str, object]:
    steps: List[Dict[str, object]] = []

    cluster_exists = _kind_cluster_exists(cluster_name)
    if not cluster_exists and create_if_missing:
        create_step = _run_command([KIND_BIN, "create", "cluster", "--name", cluster_name, "--wait", "240s"])
        steps.append(create_step.__dict__)
        if not create_step.ok:
            return {
                "ok": False,
                "cluster_name": cluster_name,
                "namespace": namespace,
                "steps": steps,
                "error": create_step.stderr or "Failed to create kind cluster",
            }

    context = f"kind-{cluster_name}"

    context_step = _run_command([KUBECTL_BIN, "config", "use-context", context])
    steps.append(context_step.__dict__)
    if not context_step.ok:
        return {
            "ok": False,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "steps": steps,
            "error": context_step.stderr or f"Unable to switch kubectl context to {context}",
        }

    ready_step = _wait_for_ready(context=context, timeout_seconds=180)
    steps.append(ready_step.__dict__)
    if not ready_step.ok:
        return {
            "ok": False,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "steps": steps,
            "error": ready_step.stderr or "Cluster did not become ready",
        }

    namespace_step = _run_command(_kubectl(["apply", "-f", str(NAMESPACE_MANIFEST)], context=context))
    steps.append(namespace_step.__dict__)
    if not namespace_step.ok:
        return {
            "ok": False,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "steps": steps,
            "error": namespace_step.stderr or "Failed to apply namespace manifest",
        }

    # Clean slate: delete existing manifests to remove old pods/crash loops
    _run_command(_kubectl(["delete", "-k", str(KUSTOMIZE_DIR), "--ignore-not-found=true"], context=context))

    manifests_step = _run_command(_kubectl(["apply", "-k", str(KUSTOMIZE_DIR)], context=context))
    steps.append(manifests_step.__dict__)
    if not manifests_step.ok:
        return {
            "ok": False,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "steps": steps,
            "error": manifests_step.stderr or "Failed to apply kustomize manifests",
        }

    wait_pods_step = _run_command(
        _kubectl(
            [
                "wait",
                "--for=condition=Available",
                "deployment/gateway",
                "deployment/orders",
                "deployment/payments",
                "-n",
                namespace,
                "--timeout=180s",
            ],
            context=context,
        )
    )
    steps.append(wait_pods_step.__dict__)
    if not wait_pods_step.ok:
        return {
            "ok": False,
            "cluster_name": cluster_name,
            "namespace": namespace,
            "steps": steps,
            "error": wait_pods_step.stderr or "Workloads did not become available",
        }

    traffic_result = None
    if warmup_traffic:
        traffic_module = import_module("tools.traffic_emulator")
        traffic_result = traffic_module.run_traffic_emulator(
            namespace=namespace,
            requests_per_service=warmup_requests_per_service,
            interval_seconds=warmup_interval_seconds,
            request_timeout_seconds=warmup_timeout_seconds,
        )

    return {
        "ok": True,
        "cluster_name": cluster_name,
        "namespace": namespace,
        "context": context,
        "warmup_traffic": warmup_traffic,
        "traffic_result": traffic_result,
        "steps": steps,
    }