"""Tool wrappers for AI agent integration with Kubernetes operations."""

from __future__ import annotations

from typing import Dict, List, Optional

try:
    from ..tools import (
        collect_evidence_snapshot as collect_evidence,
        get_cluster_snapshot as get_cluster_status,
        inject_fault,
        revert_fault,
        list_scenarios,
        monitor_cluster_health,
    )
except ImportError:
    from tools import (  # type: ignore[no-redef]
        collect_evidence_snapshot as collect_evidence,
        get_cluster_snapshot as get_cluster_status,
        inject_fault,
        revert_fault,
        list_scenarios,
        monitor_cluster_health,
    )


def tool_collect_evidence_snapshot(
    namespace: str = "ai-ops",
    services: Optional[List[str]] = None,
    log_tail_lines: int = 120,
) -> Dict[str, object]:
    """
    Collect comprehensive cluster evidence.

    Args:
        namespace: Kubernetes namespace to investigate
        services: Optional list of services to focus on
        log_tail_lines: Number of log lines to collect per pod

    Returns:
        Evidence snapshot dictionary
    """
    return collect_evidence(
        namespace=namespace,
        services=services,
        log_tail_lines=log_tail_lines,
        include_describe=True,
    )


def tool_get_cluster_status(namespace: str = "ai-ops") -> Dict[str, object]:
    """
    Get quick cluster status snapshot.

    Args:
        namespace: Kubernetes namespace

    Returns:
        Cluster status dictionary
    """
    return get_cluster_status(namespace=namespace)


def tool_list_scenarios() -> Dict[str, str]:
    """
    List available fault injection scenarios.

    Returns:
        Dictionary mapping scenario keys to descriptions
    """
    return list_scenarios()


def tool_inject_fault_scenario(
    scenario: str,
    namespace: str = "ai-ops",
) -> Dict[str, object]:
    """
    Inject a fault scenario into the cluster.

    Args:
        scenario: Scenario key (e.g., 'crashloop_orders')
        namespace: Kubernetes namespace

    Returns:
        Injection result dictionary
    """
    return inject_fault(scenario_name=scenario, namespace=namespace)


def tool_revert_fault(namespace: str = "ai-ops") -> Dict[str, object]:
    """
    Revert all injected faults to baseline.

    Args:
        namespace: Kubernetes namespace

    Returns:
        Revert result dictionary
    """
    return revert_fault(namespace=namespace)


def tool_monitor_cluster(
    namespace: str = "ai-ops",
    samples: int = 3,
    interval_seconds: int = 10,
) -> Dict[str, object]:
    """
    Monitor cluster health over time.

    Args:
        namespace: Kubernetes namespace
        samples: Number of health samples to collect
        interval_seconds: Seconds between samples

    Returns:
        Monitoring result dictionary
    """
    return monitor_cluster_health(
        namespace=namespace,
        samples=samples,
        interval_seconds=interval_seconds,
    )
