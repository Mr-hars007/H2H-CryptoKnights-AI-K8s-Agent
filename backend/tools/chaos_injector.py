"""Phase 3 chaos injector for controlled Kubernetes fault scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_KUSTOMIZE_DIR = REPO_ROOT / "k8s" / "manifests"
CHAOS_MANIFESTS_DIR = REPO_ROOT / "k8s" / "chaos" / "manifests"


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    target_resource: str
    patch_file: str


def _patch_path(file_name: str) -> str:
    return str(CHAOS_MANIFESTS_DIR / file_name)


def _kubectl(command: List[str], namespace: str | None = None) -> List[str]:
    cmd = ["kubectl"]
    if namespace:
        cmd.extend(["-n", namespace])
    cmd.extend(command)
    return cmd


def _run_command(command: List[str]) -> Dict[str, str | int | bool]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "command": " ".join(command),
    }


def _baseline_apply_command() -> List[str]:
    return ["kubectl", "apply", "-k", str(BASELINE_KUSTOMIZE_DIR)]


def list_scenarios() -> Dict[str, str]:
    return {name: scenario.description for name, scenario in SCENARIOS.items()}


def inject_fault(scenario_name: str, namespace: str = "ai-ops") -> Dict[str, object]:
    scenario = SCENARIOS.get(scenario_name)
    if scenario is None:
        return {
            "ok": False,
            "error": f"Unknown scenario '{scenario_name}'. Available: {', '.join(sorted(SCENARIOS))}",
            "steps": [],
        }

    inject_commands = [
        _kubectl(
            [
                "patch",
                scenario.target_resource,
                "--type",
                "strategic",
                "--patch-file",
                _patch_path(scenario.patch_file),
            ],
            namespace=namespace,
        )
    ]

    step_results = []
    for command in inject_commands:
        result = _run_command(command)
        step_results.append(result)
        if not result["ok"]:
            return {
                "ok": False,
                "scenario": scenario.name,
                "description": scenario.description,
                "steps": step_results,
            }

    status_result = _run_command(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace))
    step_results.append(status_result)

    return {
        "ok": True,
        "scenario": scenario.name,
        "description": scenario.description,
        "steps": step_results,
    }


def revert_fault(namespace: str = "ai-ops") -> Dict[str, object]:
    step_results = []

    apply_baseline = _run_command(_baseline_apply_command())
    step_results.append(apply_baseline)
    if not apply_baseline["ok"]:
        return {"ok": False, "steps": step_results}

    rollout_restart = _run_command(_kubectl(["rollout", "restart", "deployment/gateway", "deployment/orders", "deployment/payments"], namespace=namespace))
    step_results.append(rollout_restart)

    status_result = _run_command(_kubectl(["get", "pods", "-o", "wide"], namespace=namespace))
    step_results.append(status_result)

    return {"ok": all(step["ok"] for step in step_results), "steps": step_results}


def get_cluster_snapshot(namespace: str = "ai-ops") -> Dict[str, object]:
    steps = [
        _run_command(_kubectl(["get", "pods"], namespace=namespace)),
        _run_command(_kubectl(["get", "svc"], namespace=namespace)),
        _run_command(_kubectl(["get", "events", "--sort-by=.lastTimestamp"], namespace=namespace)),
    ]
    return {"ok": all(step["ok"] for step in steps), "steps": steps}


SCENARIOS: Dict[str, Scenario] = {
    "crashloop_orders": Scenario(
        name="crashloop_orders",
        description="Force orders deployment pods to crash on startup (CrashLoopBackOff).",
        target_resource="deployment/orders",
        patch_file="crashloop-orders-patch.yaml",
    ),
    "pending_payments": Scenario(
        name="pending_payments",
        description="Oversize payments resource requests to force Pending scheduling.",
        target_resource="deployment/payments",
        patch_file="pending-payments-patch.yaml",
    ),
    "misconfigured_service_payments": Scenario(
        name="misconfigured_service_payments",
        description="Break payments Service targetPort mapping.",
        target_resource="service/payments",
        patch_file="misconfigured-service-payments-patch.yaml",
    ),
    "oomkill_gateway": Scenario(
        name="oomkill_gateway",
        description="Replace gateway container with stress workload to trigger OOMKilled restarts.",
        target_resource="deployment/gateway",
        patch_file="oomkill-gateway-patch.yaml",
    ),
}
