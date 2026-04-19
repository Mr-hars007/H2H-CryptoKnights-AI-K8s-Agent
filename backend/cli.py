"""Interactive CLI for multi-turn AI diagnosis conversations."""

from __future__ import annotations

import argparse
import os
import sys
import json
from pathlib import Path

from agent import (
    create_agent,
    ConversationMemory,
    ConversationState,
    DiagnosisTraceCallback,
)
from tools import write_trace


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")


def print_header() -> None:
    """Print welcome header."""
    print("\n" + "=" * 70)
    print("H2H CryptoKnights: AI Kubernetes Diagnosis Assistant")
    print("Phase 5: AI Diagnosis Loop - Interactive Mode")
    print("=" * 70)
    print("\nAvailable commands:")
    print("  Type your question to diagnose cluster issues")
    print("  'mode chaos'    - Switch to Chaos Mode (for fault injection)")
    print("  'mode diagnosis' - Switch to Diagnosis Mode")
    print("  'status'        - Get current cluster status")
    print("  'scenarios'     - List available chaos scenarios")
    print("  'save'          - Save conversation to file")
    print("  'load <file>'   - Load previous conversation")
    print("  'clear'         - Clear conversation history")
    print("  'history'       - Show conversation history")
    print("  'exit'          - Exit the program")
    print("\n" + "-" * 70 + "\n")


def print_diagnosis(result: dict) -> None:
    """Pretty-print diagnosis result."""
    if not result["ok"]:
        print(f"\n❌ Error: {result.get('error', 'Unknown error')}\n")
        return
    
    diagnosis = result.get("diagnosis", "")
    print(f"\n🔍 Diagnosis:\n{diagnosis}\n")
    
    # Print trace events if available
    trace = result.get("trace", [])
    if trace:
        print("\n📋 Reasoning Trace:")
        for event in trace[-5:]:  # Show last 5 events
            event_type = event.get("event", "unknown")
            timestamp = event.get("timestamp", "?")[:19]
            if event_type == "tool_start":
                tool = event.get("tool", "?")
                print(f"  [{timestamp}] 🔧 Calling tool: {tool}")
            elif event_type == "agent_action":
                action = event.get("action", "?")
                print(f"  [{timestamp}] ✓ Agent action: {action}")
            elif event_type == "agent_finish":
                print(f"  [{timestamp}] ✅ Diagnosis complete")
        print()


def handle_special_command(cmd: str, agent, memory: ConversationMemory, state: ConversationState):
    """Handle special CLI commands."""
    cmd = cmd.strip().lower()
    
    if cmd == "exit":
        print("Saving conversation before exit...")
        filepath = memory.save()
        print(f"✅ Conversation saved to: {filepath}")
        raise SystemExit(0)
    
    elif cmd == "status":
        print("\n📊 Current Cluster Status:")
        from tools import get_cluster_snapshot
        result = get_cluster_snapshot(namespace=state.namespace)
        for step in result.get("steps", []):
            stdout = step.get("stdout", "")
            if stdout:
                print(stdout[:500])
        print()
    
    elif cmd == "scenarios":
        print("\n🎯 Available Chaos Scenarios:")
        from tools import list_scenarios
        scenarios = list_scenarios()
        for key, desc in scenarios.items():
            print(f"  • {key}: {desc}")
        print()
    
    elif cmd == "save":
        filepath = memory.save()
        print(f"✅ Conversation saved to: {filepath}\n")
    
    elif cmd.startswith("load "):
        filepath = cmd[5:].strip()
        try:
            memory = ConversationMemory.load(Path(filepath))
            print(f"✅ Loaded conversation from: {filepath}")
            print(f"   Previous turns: {len(memory.messages)}")
            print()
        except Exception as e:
            print(f"❌ Failed to load conversation: {e}\n")
    
    elif cmd == "clear":
        memory.messages.clear()
        memory.context = {"namespace": state.namespace, "focus_services": [], "known_issues": []}
        print("✅ Conversation history cleared\n")
    
    elif cmd == "history":
        if not memory.messages:
            print("No conversation history.\n")
        else:
            print("\n📝 Conversation History:")
            for i, msg in enumerate(memory.messages, 1):
                role = msg["role"].upper()
                content = msg["content"][:100]
                print(f"{i}. {role}: {content}...")
            print()
    
    elif cmd.startswith("mode "):
        new_mode = cmd[5:].strip().lower()
        if new_mode in ["diagnosis", "chaos"]:
            state.mode = new_mode
            print(f"✅ Switched to {new_mode.upper()} Mode\n")
        else:
            print(f"❌ Unknown mode: {new_mode}. Use 'diagnosis' or 'chaos'\n")
    
    else:
        return False
    
    return True


def main() -> None:
    """Main interactive CLI loop."""
    parser = argparse.ArgumentParser(
        description="Interactive Kubernetes diagnosis assistant",
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--model",
        default="llama2",
        help="Ollama model to use (default: llama2)",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:11434",
        help="Ollama base URL (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--load",
        help="Load conversation from file",
    )
    args = parser.parse_args()

    print_header()

    # Initialize agent, memory, and state
    print("🚀 Initializing AI diagnosis agent...")
    try:
        agent = create_agent(namespace=args.namespace)
        print("✅ Agent initialized successfully\n")
    except Exception as e:
        print(f"❌ Failed to initialize agent: {e}")
        print("   Make sure Ollama is running at: http://localhost:11434")
        raise SystemExit(1)

    memory = ConversationMemory()
    state = ConversationState()
    state.namespace = args.namespace

    # Load previous conversation if specified
    if args.load:
        try:
            memory = ConversationMemory.load(Path(args.load))
            print(f"✅ Loaded previous conversation with {len(memory.messages)} turns\n")
        except Exception as e:
            print(f"⚠️  Could not load conversation: {e}\n")

    # Main conversation loop
    while True:
        try:
            # Get user input
            prompt = f"[{state.mode.upper()}] > "
            user_input = input(prompt).strip()

            if not user_input:
                continue

            # Handle special commands
            if user_input.startswith("/") or user_input.startswith("-"):
                cmd = user_input.lstrip("/ ").strip()
                if handle_special_command(cmd, agent, memory, state):
                    continue

            # Regular diagnosis query
            memory.add_user_message(user_input)

            print("\n⏳ Analyzing cluster (this may take 30-60 seconds)...\n")

            # Run diagnosis with trace callback
            trace_callback = DiagnosisTraceCallback()
            result = agent.diagnose(user_input, trace_callback=trace_callback)

            # Print diagnosis
            print_diagnosis(result)

            # Save to memory and write trace
            memory.add_assistant_message(
                diagnosis=result.get("diagnosis", ""),
                trace=result.get("trace", []),
            )

            # Write trace to disk
            write_trace(
                trace_type="diagnosis",
                payload={
                    "question": user_input,
                    "diagnosis": result.get("diagnosis", "")[:500],
                    "trace_events": len(result.get("trace", [])),
                },
                metadata={
                    "namespace": args.namespace,
                    "conversation_id": memory.conversation_id,
                    "mode": state.mode,
                },
            )

            # Update context
            if "root cause" in result.get("diagnosis", "").lower():
                state.root_cause_identified = True

        except KeyboardInterrupt:
            print("\n\n👋 Saving conversation and exiting...")
            filepath = memory.save()
            print(f"✅ Conversation saved to: {filepath}")
            raise SystemExit(0)
        except EOFError:
            print("\n👋 Exiting...")
            filepath = memory.save()
            print(f"✅ Conversation saved to: {filepath}")
            raise SystemExit(0)
        except Exception as e:
            print(f"\n❌ Error during diagnosis: {e}\n")


if __name__ == "__main__":
    main()
