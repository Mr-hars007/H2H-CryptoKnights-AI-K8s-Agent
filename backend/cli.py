"""Interactive CLI for multi-turn AI diagnosis conversations with enhanced UX."""

from __future__ import annotations

import argparse
import os
import sys
import json
import textwrap
from pathlib import Path
from typing import Optional, Callable

try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    HAS_COLORAMA = True
except ImportError:
    HAS_COLORAMA = False

from agent import (
    create_agent,
    ConversationMemory,
    ConversationState,
    DiagnosisTraceCallback,
)
from tools import write_trace


DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


class Colors:
    """Color constants for terminal output."""
    if HAS_COLORAMA:
        SUCCESS = Fore.GREEN
        ERROR = Fore.RED
        WARNING = Fore.YELLOW
        INFO = Fore.CYAN
        HEADER = Fore.MAGENTA
        RESET = Style.RESET_ALL
        BOLD = Style.BRIGHT
    else:
        SUCCESS = ""
        ERROR = ""
        WARNING = ""
        INFO = ""
        HEADER = ""
        RESET = ""
        BOLD = ""


def print_header() -> None:
    """Print welcome header with enhanced formatting."""
    print("\n" + "=" * 80)
    print(f"{Colors.HEADER}{Colors.BOLD}ClusterSage{Colors.RESET}")
    print(f"{Colors.HEADER}AI Kubernetes Diagnosis and Resilience Assistant{Colors.RESET}")
    print("=" * 80)
    
    print(f"\n{Colors.BOLD}Available Commands:{Colors.RESET}")
    print(f"  {Colors.INFO}Your Question{Colors.RESET}")
    print(f"    → Diagnose cluster issues (e.g., 'Why are orders pods failing?')")
    print()
    print(f"  {Colors.INFO}Mode Management:{Colors.RESET}")
    print(f"    /mode diagnosis    - Switch to Diagnosis Mode (default)")
    print(f"    /mode chaos        - Switch to Chaos Mode (for fault injection)")
    print()
    print(f"  {Colors.INFO}Cluster Information:{Colors.RESET}")
    print(f"    /status           - Get current cluster status")
    print(f"    /discover         - Discover live services in namespace")
    print(f"    /traffic          - Generate real traffic to live services")
    print(f"    /scenarios        - List available chaos scenarios")
    print()
    print(f"  {Colors.INFO}Conversation Management:{Colors.RESET}")
    print(f"    /save             - Save current conversation to file")
    print(f"    /load <file>      - Load a previous conversation")
    print(f"    /history          - Show conversation history")
    print(f"    /clear            - Clear conversation history")
    print(f"    /settings         - Display current settings")
    print()
    print(f"  {Colors.INFO}Help & Exit:{Colors.RESET}")
    print(f"    /help             - Show this help message")
    print(f"    /exit             - Exit the program")
    print("\n" + "-" * 80 + "\n")


def print_section(title: str) -> None:
    """Print a formatted section header."""
    print(f"\n{Colors.BOLD}{Colors.INFO}{'=' * 80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.HEADER}{title:^80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.INFO}{'=' * 80}{Colors.RESET}\n")


def print_success(message: str) -> None:
    """Print a success message."""
    print(f"{Colors.SUCCESS}✅ {message}{Colors.RESET}")


def print_error(message: str) -> None:
    """Print an error message."""
    print(f"{Colors.ERROR}❌ {message}{Colors.RESET}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"{Colors.WARNING}⚠️  {message}{Colors.RESET}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"{Colors.INFO}ℹ️  {message}{Colors.RESET}")


def wrap_text(text: str, width: int = 75) -> str:
    """Wrap text to specified width."""
    lines = text.split('\n')
    wrapped = []
    for line in lines:
        if line.strip():
            wrapped.extend(textwrap.wrap(line, width=width))
        else:
            wrapped.append('')
    return '\n'.join(wrapped)


def print_diagnosis(result: dict) -> None:
    """Pretty-print diagnosis result with enhanced formatting."""
    if not result["ok"]:
        print_error(result.get('error', 'Unknown error'))
        return
    
    print_section("DIAGNOSIS RESULT")
    
    diagnosis = result.get("diagnosis", "")
    if diagnosis:
        print(wrap_text(diagnosis))
    
    # Print trace events if available
    trace = result.get("trace", [])
    if trace:
        print_section("REASONING TRACE")
        
        tool_calls = []
        actions = []
        
        for event in trace:
            event_type = event.get("event", "unknown")
            timestamp = event.get("timestamp", "?")[:19]
            
            if event_type == "tool_start":
                tool = event.get("tool", "?")
                tool_calls.append((timestamp, tool))
            elif event_type == "agent_action":
                action = event.get("action", "?")
                actions.append((timestamp, action))
        
        if tool_calls:
            print(f"{Colors.INFO}Tool Invocations:{Colors.RESET}")
            for timestamp, tool in tool_calls:
                print(f"  • [{timestamp}] {Colors.BOLD}{tool}{Colors.RESET}")
        
        if actions:
            print(f"\n{Colors.INFO}Agent Actions:{Colors.RESET}")
            for timestamp, action in actions:
                print(f"  • [{timestamp}] {action[:60]}...")
        
        print(f"\n{Colors.SUCCESS}✓ Diagnosis reasoning complete{Colors.RESET}")
    
    print()


def validate_command(cmd: str) -> tuple[bool, Optional[str]]:
    """Validate command syntax and return (is_valid, error_message)."""
    cmd = cmd.strip().lower()
    
    # Command validation rules
    if cmd.startswith("load ") and len(cmd) <= 5:
        return False, "load: Please specify a file path"
    
    if cmd.startswith("mode "):
        mode = cmd[5:].strip().lower()
        if mode not in ["diagnosis", "chaos"]:
            return False, f"mode: Unknown mode '{mode}'. Use 'diagnosis' or 'chaos'"
    
    valid_commands = [
        "exit",
        "status",
        "discover",
        "traffic",
        "scenarios",
        "save",
        "clear",
        "history",
        "help",
        "settings",
    ]
    if any(cmd == c for c in valid_commands) or cmd.startswith(("load ", "mode ")):
        return True, None
    
    return True, None



def handle_special_command(cmd: str, agent, memory: ConversationMemory, state: ConversationState) -> bool:
    """Handle special CLI commands with enhanced feedback."""
    cmd = cmd.strip().lower()
    
    # Validate command
    is_valid, error_msg = validate_command(cmd)
    if not is_valid:
        print_error(error_msg)
        return True
    
    if cmd == "exit":
        print_info("Saving conversation before exit...")
        filepath = memory.save()
        print_success(f"Conversation saved to: {filepath}")
        print("\n👋 Goodbye!\n")
        raise SystemExit(0)
    
    elif cmd == "help":
        print_header()
        return True
    
    elif cmd == "status":
        print_section("CLUSTER STATUS")
        from tools import get_cluster_snapshot
        try:
            result = get_cluster_snapshot(namespace=state.namespace)
            for step in result.get("steps", []):
                stdout = step.get("stdout", "")
                if stdout:
                    print(stdout[:700])
            print()
        except Exception as e:
            print_error(f"Failed to get cluster status: {e}")
        return True
    
    elif cmd == "scenarios":
        print_section("CHAOS SCENARIOS")
        from tools import list_scenarios
        try:
            scenarios = list_scenarios()
            for key, desc in scenarios.items():
                print(f"  {Colors.BOLD}{key:30}{Colors.RESET} {desc}")
            print()
        except Exception as e:
            print_error(f"Failed to list scenarios: {e}")
        return True

    elif cmd == "discover":
        print_section("LIVE SERVICE DISCOVERY")
        from tools import discover_services
        try:
            result = discover_services(namespace=state.namespace, require_selector=True)
            if result.get("ok"):
                services = result.get("services", [])
                if services:
                    for name in services:
                        print(f"  • {name}")
                else:
                    print_warning("No selector-backed services discovered in this namespace.")
            else:
                print_error(result.get("error", "Failed to discover services"))
            print()
        except Exception as e:
            print_error(f"Failed to discover services: {e}")
        return True

    elif cmd == "traffic":
        print_section("LIVE TRAFFIC EMULATOR")
        from tools import run_traffic_emulator
        try:
            print_info("Generating in-cluster traffic to live service endpoints...")
            result = run_traffic_emulator(namespace=state.namespace)
            if result.get("ok"):
                summary = result.get("traffic_summary", {})
                print_success("Traffic generation completed successfully")
                print_info(f"Requests observed: {summary.get('records', 0)}")
                print_info(f"Success rate: {summary.get('success_rate', 0.0) * 100:.1f}%")
            else:
                print_error(result.get("error", "Traffic generation failed"))
            print()
        except Exception as e:
            print_error(f"Failed to run traffic emulator: {e}")
        return True
    
    elif cmd == "save":
        filepath = memory.save()
        print_success(f"Conversation saved to: {filepath}")
        print()
        return True
    
    elif cmd.startswith("load "):
        filepath = cmd[5:].strip()
        try:
            memory = ConversationMemory.load(Path(filepath))
            print_success(f"Loaded conversation from: {filepath}")
            print_info(f"Previous turns: {len(memory.messages)}")
            print()
        except FileNotFoundError:
            print_error(f"File not found: {filepath}")
        except Exception as e:
            print_error(f"Failed to load conversation: {e}")
        return True
    
    elif cmd == "clear":
        memory.messages.clear()
        memory.context = {"namespace": state.namespace, "focus_services": [], "known_issues": []}
        print_success("Conversation history cleared")
        print()
        return True
    
    elif cmd == "history":
        if not memory.messages:
            print_info("No conversation history yet.")
        else:
            print_section("CONVERSATION HISTORY")
            for i, msg in enumerate(memory.messages, 1):
                role = msg["role"].upper()
                content = msg["content"][:80]
                prefix = "👤" if role == "USER" else "🤖"
                print(f"{i}. {prefix} {Colors.BOLD}{role}{Colors.RESET}: {content}...")
        print()
        return True
    
    elif cmd == "settings":
        print_section("CURRENT SETTINGS")
        print(f"  {Colors.BOLD}Namespace:{Colors.RESET}     {state.namespace}")
        print(f"  {Colors.BOLD}Mode:{Colors.RESET}          {state.mode.upper()}")
        print(f"  {Colors.BOLD}Conversation ID:{Colors.RESET} {memory.conversation_id[:8]}...")
        print(f"  {Colors.BOLD}Message Count:{Colors.RESET}  {len(memory.messages)}")
        print()
        return True
    
    elif cmd.startswith("mode "):
        new_mode = cmd[5:].strip().lower()
        if new_mode in ["diagnosis", "chaos"]:
            state.mode = new_mode
            print_success(f"Switched to {new_mode.upper()} Mode")
            print()
        else:
            print_error(f"Unknown mode: {new_mode}. Use 'diagnosis' or 'chaos'")
        return True
    
    return False


def main(argv: Optional[list[str]] = None) -> None:
    """Main interactive CLI loop with enhanced UX."""
    parser = argparse.ArgumentParser(
        description="Interactive Kubernetes diagnosis assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              %(prog)s                          # Use default namespace (ai-ops)
              %(prog)s --namespace production   # Use different namespace
              %(prog)s --load conversation.json # Load previous conversation
        """),
    )
    parser.add_argument(
        "--namespace",
        default=DEFAULT_NAMESPACE,
        help=f"Kubernetes namespace (default: {DEFAULT_NAMESPACE})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help=f"Ollama base URL (default: {DEFAULT_OLLAMA_BASE_URL})",
    )
    parser.add_argument(
        "--load",
        help="Load conversation from file",
    )
    args = parser.parse_args(argv)

    print_header()

    # Initialize agent, memory, and state
    print_info("Initializing AI diagnosis agent...")
    try:
        agent = create_agent(
            namespace=args.namespace,
            model=args.model,
            base_url=args.base_url,
        )
        print_success("Agent initialized successfully")
        print_info(f"Namespace: {args.namespace}")
        print_info(f"Model: {args.model}")
        print_info(f"Ollama URL: {args.base_url}")
        print()
    except Exception as e:
        print_error(f"Failed to initialize agent: {e}")
        print_info("Make sure Ollama is running at: http://localhost:11434")
        print_info("You can start it with: ollama serve")
        raise SystemExit(1)

    memory = ConversationMemory()
    state = ConversationState()
    state.namespace = args.namespace

    # Load previous conversation if specified
    if args.load:
        try:
            memory = ConversationMemory.load(Path(args.load))
            print_success(f"Loaded previous conversation with {len(memory.messages)} turns")
            print()
        except Exception as e:
            print_warning(f"Could not load conversation: {e}")
            print()

    # Main conversation loop
    turn_count = 0
    while True:
        try:
            # Get user input with mode indicator
            prompt = f"{Colors.BOLD}[{state.mode.upper()}]{Colors.RESET} > "
            user_input = input(prompt).strip()

            if not user_input:
                continue

            # Check for commands (/ or -)
            if user_input.startswith("/") or user_input.startswith("-"):
                cmd = user_input.lstrip("/ -").strip()
                if handle_special_command(cmd, agent, memory, state):
                    continue
                else:
                    print_warning(f"Unknown command: {cmd}. Type '/help' for available commands.")
                    continue

            # Regular diagnosis query
            turn_count += 1
            memory.add_user_message(user_input)

            print(f"\n{Colors.INFO}⏳ Analyzing cluster (this may take 30-60 seconds)...{Colors.RESET}\n")

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
                    "turn": turn_count,
                },
            )

            # Update context
            if "root cause" in result.get("diagnosis", "").lower():
                state.root_cause_identified = True
                print_success("Root cause identified in diagnosis")
            
            print_info(f"Turn {turn_count} complete. Type '/help' for commands or ask another question.")
            print()

        except KeyboardInterrupt:
            print("\n\n👋 Saving conversation and exiting...")
            filepath = memory.save()
            print_success(f"Conversation saved to: {filepath}")
            print("\n")
            raise SystemExit(0)
        except EOFError:
            print("\n👋 Exiting...")
            filepath = memory.save()
            print_success(f"Conversation saved to: {filepath}")
            print("\n")
            raise SystemExit(0)
        except Exception as e:
            print_error(f"Error during diagnosis: {e}")
            print_info("The conversation has been saved. Check logs for details.")
            print()


if __name__ == "__main__":
    main()
