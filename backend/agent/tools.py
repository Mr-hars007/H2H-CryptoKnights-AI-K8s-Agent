"""Tool wrappers for AI agent integration with Kubernetes operations."""

from __future__ import annotations

from typing import Dict, List, Optional

try:
    from ..tools import (
        collect_evidence_snapshot as collect_evidence,
        discover_services,
        get_cluster_snapshot as get_cluster_status,
        inject_fault,
        run_traffic_emulator,
        revert_fault,
        list_scenarios,
        monitor_cluster_health,
    )
except ImportError:
    from tools import (  # type: ignore[no-redef]
        collect_evidence_snapshot as collect_evidence,
        discover_services,
        get_cluster_snapshot as get_cluster_status,
        inject_fault,
        run_traffic_emulator,
        revert_fault,
        list_scenarios,
        monitor_cluster_health,
    )


def tool_collect_evidence_snapshot(
    namespace: str = "ai-ops",
    services: Optional[List[str]] = None,
    log_tail_lines: int = 60,
    include_describe: bool = False,
) -> Dict[str, object]:
    """
    Collect comprehensive cluster evidence.

    Args:
        namespace: Kubernetes namespace to investigate
        services: Optional list of services to focus on
        log_tail_lines: Number of log lines to collect per pod
        include_describe: Whether to include kubectl describe output

    Returns:
        Evidence snapshot dictionary
    """
    return collect_evidence(
        namespace=namespace,
        services=services,
        log_tail_lines=log_tail_lines,
        include_describe=include_describe,
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


def tool_discover_services(namespace: str = "ai-ops") -> Dict[str, object]:
    """
    Discover live Kubernetes services in a namespace.

    Args:
        namespace: Kubernetes namespace

    Returns:
        Service discovery result
    """
    return discover_services(namespace=namespace, require_selector=True)


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


def tool_generate_live_traffic(
    namespace: str = "ai-ops",
    services: Optional[List[str]] = None,
    requests_per_service: int = 20,
    interval_seconds: int = 1,
    request_timeout_seconds: int = 2,
) -> Dict[str, object]:
    """
    Generate real in-cluster traffic against discovered services.

    Args:
        namespace: Kubernetes namespace
        services: Optional list of target services
        requests_per_service: Request count per service
        interval_seconds: Pause between request rounds
        request_timeout_seconds: Curl timeout per request

    Returns:
        Traffic generation result with logs and summary
    """
    return run_traffic_emulator(
        namespace=namespace,
        services=services,
        requests_per_service=requests_per_service,
        interval_seconds=interval_seconds,
        request_timeout_seconds=request_timeout_seconds,
    )
