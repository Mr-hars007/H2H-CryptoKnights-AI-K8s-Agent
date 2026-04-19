"""Entry point for the AI K8s backend service."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from tools import (
    collect_evidence_snapshot,
    get_cluster_snapshot,
    inject_fault,
    list_scenarios,
    list_traces,
    monitor_cluster_health,
    read_trace,
    revert_fault,
    write_trace,
)
from agent import create_agent, DiagnosisTraceCallback


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
DEFAULT_MONITOR_SAMPLES = int(os.getenv("AI_MONITOR_SAMPLES", "3"))
DEFAULT_MONITOR_INTERVAL_SECONDS = int(os.getenv("AI_MONITOR_INTERVAL_SECONDS", "10"))
DEFAULT_LOG_TAIL_LINES = int(os.getenv("AI_LOG_TAIL_LINES", "120"))
DEFAULT_TRACE_LIST_LIMIT = int(os.getenv("AI_TRACE_LIST_LIMIT", "20"))


def _parse_services_arg(raw_value: str | None) -> list[str] | None:
    if not raw_value:
        return None
    parsed = [item.strip() for item in raw_value.split(",") if item.strip()]
    return parsed or None


def _print_result(result: Dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="H2H CryptoKnights AI K8s Agent - Phase 5 diagnosis integration",
    )
    parser.add_argument(
        "command",
        choices=["list", "inject", "revert", "status", "snapshot", "monitor", "traces", "trace", "diagnose", "cli"],
        help="Operation to run",
    )
    parser.add_argument(
        "--scenario",
        help="Scenario key used by the inject command",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=DEFAULT_MONITOR_SAMPLES,
        help=f"Number of health samples for monitor command (default: {DEFAULT_MONITOR_SAMPLES})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_MONITOR_INTERVAL_SECONDS,
        help=(
            f"Seconds between monitor samples (default: {DEFAULT_MONITOR_INTERVAL_SECONDS})"
        ),
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_LOG_TAIL_LINES,
        help=f"Log tail lines for snapshot command (default: {DEFAULT_LOG_TAIL_LINES})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TRACE_LIST_LIMIT,
        help=f"Maximum traces returned by traces command (default: {DEFAULT_TRACE_LIST_LIMIT})",
    )
    parser.add_argument(
        "--services",
        help="Comma-separated service list override for snapshot (e.g. gateway,orders,payments)",
    )
    parser.add_argument(
        "--trace-type",
        help="Optional trace type filter for traces command",
    )
    parser.add_argument(
        "--trace-id",
        help="Trace ID for trace command",
    )
    parser.add_argument(
        "--no-describe",
        action="store_true",
        help="Skip kubectl describe commands during snapshot collection",
    )
    parser.add_argument(
        "--question",
        help="Natural language question for diagnose command",
    )
    return parser


def _with_trace(command: str, payload: Dict[str, Any], namespace: str) -> Dict[str, Any]:
    trace = write_trace(
        trace_type=command,
        payload=payload,
        metadata={
            "namespace": namespace,
            "command": command,
        },
    )
    return {
        **payload,
        "trace": trace,
    }


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "list":
        result = {"ok": True, "scenarios": list_scenarios()}
        _print_result(_with_trace(command="list", payload=result, namespace=args.namespace))
        return

    if args.command == "inject":
        if not args.scenario:
            _print_result(
                {
                    "ok": False,
                    "error": "--scenario is required when command is inject",
                }
            )
            raise SystemExit(2)
        result = inject_fault(args.scenario, namespace=args.namespace)
        _print_result(_with_trace(command="inject", payload=result, namespace=args.namespace))
        return

    if args.command == "revert":
        result = revert_fault(namespace=args.namespace)
        _print_result(_with_trace(command="revert", payload=result, namespace=args.namespace))
        return

    if args.command == "status":
        result = get_cluster_snapshot(namespace=args.namespace)
        _print_result(_with_trace(command="status", payload=result, namespace=args.namespace))
        return

    if args.command == "snapshot":
        services = _parse_services_arg(args.services)
        result = collect_evidence_snapshot(
            namespace=args.namespace,
            services=services,
            log_tail_lines=args.tail,
            include_describe=not args.no_describe,
        )
        _print_result(_with_trace(command="snapshot", payload=result, namespace=args.namespace))
        return

    if args.command == "monitor":
        result = monitor_cluster_health(
            namespace=args.namespace,
            samples=args.samples,
            interval_seconds=args.interval,
        )
        _print_result(_with_trace(command="monitor", payload=result, namespace=args.namespace))
        return

    if args.command == "traces":
        _print_result(list_traces(limit=args.limit, trace_type=args.trace_type))
        return

    if args.command == "trace":
        if not args.trace_id:
            _print_result(
                {
                    "ok": False,
                    "error": "--trace-id is required when command is trace",
                }
            )
            raise SystemExit(2)
        _print_result(read_trace(trace_id=args.trace_id))
        return

    if args.command == "diagnose":
        if not args.question:
            _print_result(
                {
                    "ok": False,
                    "error": "--question is required when command is diagnose",
                }
            )
            raise SystemExit(2)
        
        print("🚀 Initializing AI diagnosis agent...", file=__import__("sys").stderr)
        try:
            agent = create_agent(namespace=args.namespace)
        except Exception as e:
            _print_result({
                "ok": False,
                "error": f"Failed to initialize agent: {e}",
            })
            raise SystemExit(1)
        
        print("⏳ Analyzing cluster...", file=__import__("sys").stderr)
        trace_callback = DiagnosisTraceCallback()
        result = agent.diagnose(args.question, trace_callback=trace_callback)
        
        # Write trace to disk
        write_trace(
            trace_type="diagnosis",
            payload={
                "question": args.question,
                "diagnosis": result.get("diagnosis", "")[:500],
                "trace_events": len(result.get("trace", [])),
            },
            metadata={
                "namespace": args.namespace,
                "command": "diagnose",
            },
        )
        
        _print_result(result)
        return

    if args.command == "cli":
        print("🚀 Launching interactive diagnosis CLI...", file=__import__("sys").stderr)
        from cli import main as cli_main
        cli_main()
        return


if __name__ == "__main__":
    main()
