"""Entry point for the AI K8s backend service."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from tools import get_cluster_snapshot, inject_fault, list_scenarios, revert_fault


def _print_result(result: Dict[str, Any]) -> None:
    print(json.dumps(result, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="H2H CryptoKnights AI K8s Agent - Phase 3 chaos controller",
    )
    parser.add_argument(
        "command",
        choices=["list", "inject", "revert", "status"],
        help="Chaos operation to run",
    )
    parser.add_argument(
        "--scenario",
        help="Scenario key used by the inject command",
    )
    parser.add_argument(
        "--namespace",
        default="ai-ops",
        help="Kubernetes namespace (default: ai-ops)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "list":
        _print_result({"ok": True, "scenarios": list_scenarios()})
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
        _print_result(inject_fault(args.scenario, namespace=args.namespace))
        return

    if args.command == "revert":
        _print_result(revert_fault(namespace=args.namespace))
        return

    _print_result(get_cluster_snapshot(namespace=args.namespace))


if __name__ == "__main__":
    main()
