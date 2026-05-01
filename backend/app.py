"""Entry point for the AI K8s backend service."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from tools import (
    collect_evidence_snapshot,
    discover_services,
    get_cluster_snapshot,
    inject_fault,
    list_scenarios,
    list_traces,
    monitor_cluster_health,
    read_trace,
    run_traffic_emulator,
    revert_fault,
    write_trace,
)
from agent import create_agent, DiagnosisTraceCallback


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
DEFAULT_MONITOR_SAMPLES = int(os.getenv("AI_MONITOR_SAMPLES", "3"))
DEFAULT_MONITOR_INTERVAL_SECONDS = int(os.getenv("AI_MONITOR_INTERVAL_SECONDS", "10"))
DEFAULT_LOG_TAIL_LINES = int(os.getenv("AI_LOG_TAIL_LINES", "120"))
DEFAULT_TRACE_LIST_LIMIT = int(os.getenv("AI_TRACE_LIST_LIMIT", "20"))
DEFAULT_TRAFFIC_REQUESTS = int(os.getenv("AI_TRAFFIC_REQUESTS_PER_SERVICE", "20"))
DEFAULT_TRAFFIC_INTERVAL = int(os.getenv("AI_TRAFFIC_INTERVAL_SECONDS", "1"))
DEFAULT_TRAFFIC_TIMEOUT = int(os.getenv("AI_TRAFFIC_REQUEST_TIMEOUT_SECONDS", "2"))
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def _parse_services_arg(raw_value: str | None) -> list[str] | None:
    if not raw_value:
        return None
    parsed = [item.strip() for item in raw_value.split(",") if item.strip()]
    return parsed or None


def _print_result(result: Dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ClusterSage - AI Kubernetes diagnosis and chaos testing",
    )
    parser.add_argument(
        "command",
        choices=[
            "list",
            "inject",
            "revert",
            "status",
            "discover",
            "traffic",
            "snapshot",
            "monitor",
            "traces",
            "trace",
            "diagnose",
            "cli",
        ],
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
    parser.add_argument(
        "--requests-per-service",
        type=int,
        default=DEFAULT_TRAFFIC_REQUESTS,
        help=f"Traffic requests per service for traffic command (default: {DEFAULT_TRAFFIC_REQUESTS})",
    )
    parser.add_argument(
        "--traffic-interval",
        type=int,
        default=DEFAULT_TRAFFIC_INTERVAL,
        help=f"Seconds between traffic rounds (default: {DEFAULT_TRAFFIC_INTERVAL})",
    )
    parser.add_argument(
        "--request-timeout",
        type=int,
        default=DEFAULT_TRAFFIC_TIMEOUT,
        help=f"Timeout per traffic request in seconds (default: {DEFAULT_TRAFFIC_TIMEOUT})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help=f"Ollama model to use for diagnose/cli (default: {DEFAULT_OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help=f"Ollama base URL for diagnose/cli (default: {DEFAULT_OLLAMA_BASE_URL})",
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

    if args.command == "discover":
        result = discover_services(namespace=args.namespace, require_selector=True)
        _print_result(_with_trace(command="discover", payload=result, namespace=args.namespace))
        return

    if args.command == "traffic":
        result = run_traffic_emulator(
            namespace=args.namespace,
            services=_parse_services_arg(args.services),
            requests_per_service=args.requests_per_service,
            interval_seconds=args.traffic_interval,
            request_timeout_seconds=args.request_timeout,
        )
        _print_result(_with_trace(command="traffic", payload=result, namespace=args.namespace))
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
            agent = create_agent(
                namespace=args.namespace,
                model=args.model,
                base_url=args.base_url,
            )
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
        cli_main(
            argv=[
                "--namespace",
                args.namespace,
                "--model",
                args.model,
                "--base-url",
                args.base_url,
            ]
        )
        return


if __name__ == "__main__":
    main()
