from __future__ import annotations

import os
import sys
import json
import threading
import subprocess
import time
from urllib.parse import urlparse
from urllib.request import urlopen
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Robust import for Streamlit internal thread handling
try:
    from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_ctx
except ImportError:
    try:
        from streamlit.runtime.scriptrunner.script_run_context import add_script_run_context, get_script_run_ctx
    except ImportError:
        # Fallback for older versions
        try:
            from streamlit.scriptrunner import add_script_run_context, get_script_run_ctx
        except ImportError:
            add_script_run_context = None
            get_script_run_ctx = None

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import streamlit as st
import pandas as pd
import atexit
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False
from agent import create_agent, ConversationMemory, ConversationState, DiagnosisTraceCallback
from bootstrap import bootstrap_local_cluster
from tools import (
    write_trace,
    discover_services,
    get_cluster_snapshot,
    inject_fault,
    list_scenarios,
    revert_fault,
    collect_live_service_stats,
    run_traffic_emulator,
)

st.set_page_config(page_title="H2H CryptoKnights - AI K8s Diagnosis", page_icon="K8s", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.success-box { background: #d4edda; padding: 1.5rem; border-radius: 8px; border-left: 5px solid #28a745; margin: 1rem 0; }
.error-box { background: #f8d7da; padding: 1.5rem; border-radius: 8px; border-left: 5px solid #dc3545; margin: 1rem 0; }
.info-box { background: #d1ecf1; padding: 1.5rem; border-radius: 8px; border-left: 5px solid #17a2b8; margin: 1rem 0; }
.diagnosis-box { background: #f0f2f6; padding: 1.5rem; border-radius: 8px; border-left: 5px solid #4CAF50; margin: 1rem 0; }
.trace-box { background: #f5f5f5; padding: 1rem; border-radius: 4px; font-family: monospace; font-size: 0.85rem; border-left: 4px solid #666; margin: 0.5rem 0; }
</style>
""", unsafe_allow_html=True)

DIAGNOSTIC_TEMPLATES = {
    "CrashLoopBackOff": "Why are the [service] pods in CrashLoopBackOff and how do I fix them?",
    "Pending Pods": "Why are the [service] pods stuck in Pending state?",
    "Resource Issues": "Are any pods running out of memory or hitting CPU limits?",
    "Service Connectivity": "Are there any network issues between services?",
    "General Health": "What's the overall cluster health and are there any issues?",
    "Recent Failures": "What recent pod failures occurred and what caused them?",
}

CHAOS_EXAMPLES = {
    "crashloop_orders": "Simulates pod crashes in orders service",
    "pending_payments": "Simulates pods stuck pending",
    "misconfigured_service_payments": "Simulates service misconfiguration",
    "oomkill_gateway": "Simulates memory limit exceeded",
}


def _extract_diagnosis_logs(result: dict) -> List[Dict[str, str]]:
    evidence_snapshot = result.get("evidence_snapshot", {}) if isinstance(result, dict) else {}
    service_evidence = evidence_snapshot.get("service_evidence", {}) if isinstance(evidence_snapshot, dict) else {}
    log_entries: List[Dict[str, str]] = []

    for service_name, service_payload in service_evidence.items():
        if not isinstance(service_payload, dict):
            continue
        pods = service_payload.get("pods", {})
        if not isinstance(pods, dict):
            continue

        for pod_name, pod_payload in pods.items():
            if not isinstance(pod_payload, dict):
                continue
            for step in pod_payload.get("steps", []):
                command = str(step.get("command", "") or "").lower()
                if " logs " not in command and not command.endswith(" logs"):
                    continue

                stdout = str(step.get("stdout", "") or "").strip()
                signal_lines = step.get("signal_lines")
                summary_text = ""
                if isinstance(signal_lines, list) and signal_lines:
                    summary_text = "\n".join(str(line) for line in signal_lines if str(line).strip())

                log_entries.append(
                    {
                        "service": str(service_name),
                        "pod": str(pod_name),
                        "command": str(step.get("command", "") or ""),
                        "summary": summary_text,
                        "stdout": stdout,
                    }
                )

    return log_entries


def render_diagnosis_logs(result: dict) -> None:
    log_entries = _extract_diagnosis_logs(result)
    st.subheader("Collected Pod Logs")

    if not log_entries:
        st.info("No pod logs were collected for the last diagnosis result.")
        return

    st.caption(f"Showing {len(log_entries)} pod log capture(s) from the latest diagnosis.")
    for entry in log_entries:
        label = f"{entry['service']} / {entry['pod']}"
        with st.expander(label, expanded=False):
            if entry["summary"]:
                st.caption("Signal lines used by the diagnosis")
                st.code(entry["summary"], language="plaintext")
            if entry["stdout"]:
                st.caption(entry["command"])
                st.code(entry["stdout"], language="plaintext")
            else:
                st.info("This log command returned no stdout.")


def _wait_for_ollama(base_url: str, timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    tags_url = f"{base_url.rstrip('/')}/api/tags"
    while time.time() < deadline:
        try:
            with urlopen(tags_url, timeout=2) as response:
                if 200 <= getattr(response, "status", 200) < 300:
                    return True
        except Exception:
            time.sleep(1)
    return False


def restart_ollama_server(base_url: str) -> Dict[str, object]:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        return {
            "ok": False,
            "skipped": True,
            "message": f"Skipped Ollama restart because base URL host is `{host or 'unknown'}` instead of localhost.",
        }

    stop_commands = []
    if os.name == "nt":
        stop_commands.append(["taskkill", "/IM", "ollama.exe", "/F"])
    else:
        stop_commands.append(["pkill", "-f", "ollama serve"])
        stop_commands.append(["pkill", "-f", "ollama"])

    stop_results = []
    for command in stop_commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            stop_results.append(
                {
                    "command": " ".join(command),
                    "returncode": completed.returncode,
                    "stdout": (completed.stdout or "").strip(),
                    "stderr": (completed.stderr or "").strip(),
                }
            )
        except FileNotFoundError as exc:
            stop_results.append(
                {
                    "command": " ".join(command),
                    "returncode": 127,
                    "stdout": "",
                    "stderr": str(exc),
                }
            )

    time.sleep(2)

    try:
        # On Windows, try to find ollama in common locations if it's not in PATH
        ollama_cmd = "ollama"
        if os.name == "nt":
            import shutil
            if not shutil.which("ollama"):
                # Check default install path
                localappdata = os.environ.get("LOCALAPPDATA", "")
                alt_path = os.path.join(localappdata, "Ollama", "ollama.exe")
                if os.path.exists(alt_path):
                    ollama_cmd = alt_path

        subprocess.Popen(
            [ollama_cmd, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            shell=(os.name == "nt"), # Use shell on Windows to help resolve PATH
        )
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "message": f"Unable to start Ollama: {exc}",
            "steps": stop_results,
        }

    ready = _wait_for_ollama(base_url=base_url, timeout_seconds=20)
    return {
        "ok": ready,
        "skipped": False,
        "message": "Ollama restarted successfully." if ready else "Ollama restart was attempted, but the API did not become ready in time.",
        "steps": stop_results,
    }


def _parse_pod_rows(pods_stdout: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    lines = [line.strip() for line in (pods_stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return rows

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        rows.append(
            {
                "name": parts[0],
                "ready": parts[1],
                "status": parts[2],
                "restarts": parts[3],
                "age": parts[4],
            }
        )

    return rows


def _summarize_pod_health(pods: List[Dict[str, str]]) -> Dict[str, int]:
    summary = {
        "total": len(pods),
        "running": 0,
        "pending": 0,
        "failed": 0,
        "other": 0,
    }

    for pod in pods:
        status = (pod.get("status") or "").lower()
        if status == "running":
            summary["running"] += 1
        elif status == "pending":
            summary["pending"] += 1
        elif status in {"failed", "crashloopbackoff", "error", "oomkilled"}:
            summary["failed"] += 1
        else:
            summary["other"] += 1

    return summary


def _extract_pods_stdout(snapshot: Dict[str, object]) -> str:
    for step in snapshot.get("steps", []):
        command = str(step.get("command", "") or "").lower()
        if " get pods" in command:
            return str(step.get("stdout", "") or "")
    return ""


def _record_live_pod_status(namespace: str) -> tuple[List[Dict[str, str]], Dict[str, int]]:
    snapshot = get_cluster_snapshot(namespace=namespace)
    pods_stdout = _extract_pods_stdout(snapshot)
    pod_rows = _parse_pod_rows(pods_stdout)
    summary = _summarize_pod_health(pod_rows)

    st.session_state.pod_status_tick += 1
    point = {
        "tick": st.session_state.pod_status_tick,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "running": summary["running"],
        "pending": summary["pending"],
        "failed": summary["failed"],
        "other": summary["other"],
    }

    history = st.session_state.pod_status_history
    history.append(point)
    if len(history) > 180:
        del history[:-180]

    return pod_rows, summary


def render_live_pod_status_graph(namespace: str, key_prefix: str, enable_autorefresh: bool = True) -> None:
    st.subheader("Live Pod Status")
    st.caption("Auto-refreshes every second to show real cluster effects.")

    if enable_autorefresh and st.session_state.pod_monitor_auto_refresh and HAS_AUTOREFRESH:
        st_autorefresh(interval=1000, key=f"{key_prefix}_pod_autorefresh")
    elif enable_autorefresh and st.session_state.pod_monitor_auto_refresh and not HAS_AUTOREFRESH:
        st.caption("Install streamlit-autorefresh for true 1s updates. Using manual refresh fallback.")

    try:
        pod_rows, summary = _record_live_pod_status(namespace)
    except Exception as exc:
        st.error(f"Unable to fetch pod status: {exc}")
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", summary["total"])
    c2.metric("Running", summary["running"])
    c3.metric("Pending", summary["pending"])
    c4.metric("Failed", summary["failed"])
    c5.metric("Other", summary["other"])

    chart_rows = [
        {
            "tick": item["tick"],
            "timestamp": item["timestamp"],
            "Running": item["running"],
            "Pending": item["pending"],
            "Failed": item["failed"],
            "Other": item["other"],
        }
        for item in st.session_state.pod_status_history
    ]
    if chart_rows:
        chart_df = pd.DataFrame(chart_rows)
        chart_df = chart_df.set_index("tick")
        st.line_chart(chart_df[["Running", "Pending", "Failed", "Other"]], height=260)
        st.caption(f"Last updated: {chart_rows[-1]['timestamp']}")

    with st.expander("Current Pod Table", expanded=True):
        if pod_rows:
            st.table(pod_rows)
        else:
            st.info("No pod rows available yet.")


@st.cache_data(ttl=20, show_spinner=False)
def _cached_live_service_stats(namespace: str) -> dict:
    return collect_live_service_stats(namespace=namespace)


def render_live_service_stats(namespace: str) -> None:
    st.subheader("Live Service Stats")
    if st.button("Probe Live Service Stats", key="probe_live_stats", use_container_width=True):
        st.session_state.live_stats_result = _cached_live_service_stats(namespace)

    result = st.session_state.live_stats_result
    if not result:
        st.info("Click 'Probe Live Service Stats' to run a live in-cluster probe.")
        st.markdown("---")
        return

    try:
        if not result.get("ok"):
            st.warning("Unable to fetch live service stats right now.")
            return

        stats = result.get("stats", {})
        targets = result.get("targets", [])
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Services", len(targets))
        c2.metric("Avg Latency", f"{float(stats.get('avg_latency_ms', 0.0)):.0f} ms")
        c3.metric("P95 Latency", f"{float(stats.get('p95_latency_ms', 0.0)):.0f} ms")
        c4.metric("Errors", int(stats.get("errors", 0)))
        c5.metric("Traffic", f"{float(stats.get('traffic_rps', 0.0)):.1f} rps")

        with st.expander("Service Probe Details", expanded=False):
            st.dataframe(result.get("probe_records", []), use_container_width=True)
    except Exception as exc:
        st.warning(f"Live service stats unavailable: {exc}")

    st.markdown("---")

def init_session_state():
    if "agent" not in st.session_state:
        st.session_state.agent = None
    if "memory" not in st.session_state:
        st.session_state.memory = ConversationMemory()
    if "state" not in st.session_state:
        st.session_state.state = ConversationState()
    if "initialized" not in st.session_state:
        st.session_state.initialized = False
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "current_mode" not in st.session_state:
        st.session_state.current_mode = "diagnosis"
    if "bootstrap_result" not in st.session_state:
        st.session_state.bootstrap_result = None
    if "model" not in st.session_state:
        st.session_state.model = os.getenv("OLLAMA_MODEL", "qwen:7b")
    if "base_url" not in st.session_state:
        st.session_state.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    if "pod_status_history" not in st.session_state:
        st.session_state.pod_status_history = []
    if "pod_status_tick" not in st.session_state:
        st.session_state.pod_status_tick = 0
    if "pod_monitor_auto_refresh" not in st.session_state:
        st.session_state.pod_monitor_auto_refresh = True
    if "live_stats_result" not in st.session_state:
        st.session_state.live_stats_result = None
    if "traffic_emulator_started" not in st.session_state:
        st.session_state.traffic_emulator_started = False
    if "last_diagnosis_result" not in st.session_state:
        st.session_state.last_diagnosis_result = None
    if "ollama_restart_result" not in st.session_state:
        st.session_state.ollama_restart_result = None


def _run_background_traffic(namespace: str) -> None:
    try:
        run_traffic_emulator(
            namespace=namespace,
            requests_per_service=30,
            interval_seconds=1,
            request_timeout_seconds=2,
        )
    except Exception:
        # Background task should never break Streamlit flow.
        pass


def _start_background_traffic(namespace: str) -> None:
    ctx = get_script_run_ctx()
    def wrapper():
        if ctx and callable(add_script_run_context):
            add_script_run_context(threading.current_thread(), ctx)
        _run_background_traffic(namespace)
        
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()

def initialize_agent(namespace: str, model: str, base_url: str) -> bool:
    try:
        ollama_restart = restart_ollama_server(base_url=base_url)
        st.session_state.ollama_restart_result = ollama_restart
        if ollama_restart.get("ok"):
            st.info("Ollama was restarted before initialization.")
        elif ollama_restart.get("skipped"):
            st.info(str(ollama_restart.get("message", "Skipped Ollama restart.")))
        else:
            st.warning(str(ollama_restart.get("message", "Ollama restart did not complete cleanly.")))

        bootstrap_result = bootstrap_local_cluster(
            namespace=namespace,
            warmup_traffic=False,
            warmup_requests_per_service=5,
            warmup_interval_seconds=1,
            warmup_timeout_seconds=2,
        )
        st.session_state.bootstrap_result = bootstrap_result

        if not bootstrap_result.get("ok"):
            st.error(f"Bootstrap failed: {bootstrap_result.get('error', 'Unknown error')}")
            st.json(bootstrap_result, expanded=False)
            return False

        st.session_state.agent = create_agent(
            namespace=namespace,
            model=model,
            base_url=base_url,
        )
        st.session_state.state.namespace = namespace
        st.session_state.initialized = True
        st.session_state.current_mode = "diagnosis"
        st.session_state.pod_status_history = []
        st.session_state.pod_status_tick = 0
        st.session_state.traffic_emulator_started = True
        _start_background_traffic(namespace)
        st.success("Initialization complete. Traffic emulator started in background.")

        traffic_result = bootstrap_result.get("traffic_result")
        if isinstance(traffic_result, dict):
            if traffic_result.get("ok"):
                summary = traffic_result.get("traffic_summary", {})
                st.success(
                    "Traffic emulator started during initialization: "
                    f"{summary.get('records', 0)} requests observed"
                )
            else:
                st.warning(
                    "Initialization finished, but traffic emulator reported an issue: "
                    f"{traffic_result.get('error', 'unknown error')}"
                )
        return True
    except Exception as e:
        st.error(f"Failed: {str(e)}")
        st.info("Make sure Ollama is running: ollama serve")
        return False

def render_diagnosis_result(result: dict):
    diagnosis_text = result.get("diagnosis", "")
    if diagnosis_text:
        if result.get("ok"):
            st.success("Diagnosis Complete")
        else:
            st.warning("Diagnosis completed in degraded mode")
        st.markdown(f"### Analysis\n{diagnosis_text}")
        if result.get("agent_error"):
            st.caption(f"Agent issue: {result.get('agent_error')}")
        if result.get("recovery_mode"):
            st.caption(f"Recovery mode: {result.get('recovery_mode')}")
        if result.get("trace"):
            with st.expander("Trace"):
                for event in result.get("trace", []):
                    if event.get("event") == "tool_start":
                        st.text(f"Tool: {event.get('tool', '?')}")
        return

    if result.get("ok"):
        st.success("Diagnosis Complete")
    else:
        st.error(f"Failed: {result.get('error', 'Unknown error')}")

class StreamlitDiagnosisCallback(DiagnosisTraceCallback):
    """Callback that updates a Streamlit empty container with live progress."""
    def __init__(self, progress_container, response_container):
        super().__init__()
        self.progress_container = progress_container
        self.response_container = response_container
        # Safe call to get context
        self.ctx = get_script_run_ctx() if callable(get_script_run_ctx) else None
        self.current_step = ""
        self.full_response = ""
        self.is_final_answer = False

    def _ensure_context(self):
        if self.ctx and callable(add_script_run_context):
            add_script_run_context(threading.current_thread(), self.ctx)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        self._ensure_context()
        super().on_tool_start(serialized, input_str, **kwargs)
        tool_name = serialized.get("name", "unknown")
        self.current_step = f"🔍 **Running Tool:** `{tool_name}`\n\nInput: `{input_str}`"
        self._update_ui()

    def on_tool_end(self, output: str, **kwargs) -> None:
        self._ensure_context()
        super().on_tool_end(output, **kwargs)
        self.current_step = f"✅ **Tool Finished**\n\nOutput preview: `{output[:100]}...`"
        self._update_ui()

    def on_agent_action(self, action, **kwargs) -> None:
        self._ensure_context()
        super().on_agent_action(action, **kwargs)
        self.current_step = f"🤖 **AI Thinking...**\n\nAction: `{action.tool}`\n\nInput: `{action.tool_input}`"
        self._update_ui()
        self.full_response = ""
        self.is_final_answer = False

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        self._ensure_context()
        self.full_response += token
        if "Final Answer:" in self.full_response or self.is_final_answer:
            self.is_final_answer = True
            display_text = self.full_response
            if "Final Answer:" in display_text:
                display_text = display_text.split("Final Answer:", 1)[1]
            with self.response_container:
                st.markdown(f"### 🤖 Streaming Response...\n{display_text.strip()}")

    def _update_ui(self):
        self._ensure_context()
        with self.progress_container:
            st.info(self.current_step)


def render_diagnosis_mode(ns: str):
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header("Kubernetes Diagnosis")
    with col2:
        if st.button("Refresh", key="diagnosis_refresh"):
            st.rerun()
    
    st.markdown("---")
    render_live_pod_status_graph(ns, key_prefix="diagnosis", enable_autorefresh=False)
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["Diagnosis", "Status", "History"])
    
    with tab1:
        selected = st.selectbox("Template:", ["Custom"] + list(DIAGNOSTIC_TEMPLATES.keys()))
        if selected != "Custom":
            st.info(f"Template: {DIAGNOSTIC_TEMPLATES[selected]}")
        
        question = st.text_area(
            "What's wrong?",
            key="diagnosis_question",
            placeholder="e.g., Why are orders pods failing?",
            height=100,
        )

        # Container for live progress and streaming updates
        progress_container = st.empty()
        response_container = st.empty()

        if st.session_state.last_diagnosis_result is not None:
            render_diagnosis_result(st.session_state.last_diagnosis_result)
            st.markdown("---")
            render_diagnosis_logs(st.session_state.last_diagnosis_result)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Analyze", key="diagnosis_analyze", type="primary", use_container_width=True) and question:
                st.session_state.messages.append({"role": "user", "content": question})
                # Clear previous results from UI before starting
                st.session_state.last_diagnosis_result = None
                
                with st.spinner("Agent working..."):
                    try:
                        # Capture current context to inject into background threads
                        current_ctx = get_script_run_ctx()
                        def thread_init():
                            if current_ctx and callable(add_script_run_context):
                                add_script_run_context(threading.current_thread(), current_ctx)

                        # Use the new streaming callback
                        callback = StreamlitDiagnosisCallback(progress_container, response_container)
                        result = st.session_state.agent.diagnose(
                            question, 
                            trace_callback=callback,
                            thread_initializer=thread_init
                        )
                        
                        # Clear containers after completion
                        progress_container.empty()
                        response_container.empty()
                        
                        st.session_state.last_diagnosis_result = result
                        trace_record = write_trace(
                            trace_type="web-diagnosis",
                            payload=result,
                            metadata={
                                "namespace": ns,
                                "question": question,
                                "mode": "streamlit",
                            },
                        )
                        st.session_state.last_diagnosis_result["saved_trace"] = trace_record
                        if result.get("ok"):
                            st.session_state.messages.append({"role": "assistant", "content": result.get("diagnosis", "")})
                        
                        # Rerun to clear the spinner and show the final result properly
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        with col2:
            if st.button("Snapshot", key="diagnosis_snapshot"):
                with st.spinner("Fetching..."):
                    try:
                        result = get_cluster_snapshot(namespace=ns)
                        st.json(result, expanded=False)
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col3:
            if st.button("Help", key="diagnosis_help"):
                st.info("Be specific about failing service. Include symptoms like CrashLoopBackOff or Pending.")
    
    with tab2:
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Fetch Status", key="diagnosis_fetch_status"):
                with st.spinner("Fetching..."):
                    try:
                        result = get_cluster_snapshot(namespace=ns)
                        if result.get("ok"):
                            for step in result.get("steps", []):
                                stdout = step.get("stdout", "")
                                if stdout:
                                    st.code(stdout, language="plaintext")
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col2:
            if st.button("Discover Services", key="diagnosis_discover_services"):
                with st.spinner("Discovering..."):
                    try:
                        result = discover_services(namespace=ns, require_selector=True)
                        if result.get("ok"):
                            st.success("Discovered services from live cluster")
                            st.json(result, expanded=False)
                        else:
                            st.error(result.get("error", "Failed to discover services"))
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col3:
            if st.button("Generate Traffic", key="diagnosis_generate_traffic"):
                with st.spinner("Generating in-cluster traffic..."):
                    try:
                        result = run_traffic_emulator(namespace=ns)
                        if result.get("ok"):
                            st.success("Traffic generation complete")
                        else:
                            st.error(result.get("error", "Traffic generation failed"))
                        st.json(result, expanded=False)
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    with tab3:
        if st.session_state.messages:
            for i, msg in enumerate(st.session_state.messages, 1):
                icon = "User" if msg["role"] == "user" else "Assistant"
                st.write(f"**{icon} {msg['role'].title()} ({i}):** {msg['content'][:100]}...")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save", key="history_save"):
                    fp = st.session_state.memory.save()
                    st.success(f"Saved: {Path(fp).name}")
            with col2:
                if st.button("Clear", key="history_clear"):
                    st.session_state.memory.messages.clear()
                    st.session_state.messages = []
                    st.rerun()
        else:
            st.info("No history yet.")

def render_chaos_mode(ns: str):
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header("Chaos Testing")
    with col2:
        if st.button("Refresh", key="chaos_refresh"):
            st.rerun()
    
    st.markdown("---")
    render_live_pod_status_graph(ns, key_prefix="chaos")
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["Inject", "Manage", "Scenarios"])
    
    with tab1:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Select & Inject")
            try:
                scen = list_scenarios()
                selected = st.selectbox("Fault:", list(scen.keys()))
                if selected:
                    st.info(CHAOS_EXAMPLES.get(selected, scen.get(selected, "No desc")))
                
                if st.button("Inject", key="chaos_inject", type="primary", use_container_width=True):
                    with st.spinner(f"Injecting {selected}..."):
                        result = inject_fault(selected, namespace=ns)
                        if result.get("ok"):
                            st.success(f"Injected: {selected}")
                        else:
                            st.error(f"Failed: {result.get('error')}")
            except Exception as e:
                st.error(f"Error: {e}")
        
        with col2:
            st.subheader("Workflow")
            st.markdown("1. Select scenario\n2. Click Inject\n3. Switch to Diagnosis\n4. Ask why it failed\n5. Revert faults\n6. Verify recovery")
    
    with tab2:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Revert All", key="chaos_revert_all", type="primary", use_container_width=True):
                with st.spinner("Reverting..."):
                    try:
                        result = revert_fault(namespace=ns)
                        if result.get("ok"):
                            st.success("All faults reverted")
                        else:
                            st.error(f"Failed: {result.get('error')}")
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col2:
            if st.button("State", key="chaos_state", use_container_width=True):
                with st.spinner("Fetching..."):
                    try:
                        result = get_cluster_snapshot(namespace=ns)
                        st.json(result, expanded=False)
                    except Exception as e:
                        st.error(f"Error: {e}")
    
    with tab3:
        st.subheader("Scenarios")
        try:
            scen = list_scenarios()
            for key, desc in scen.items():
                with st.expander(f"Scenario: {key}"):
                    st.write(f"**Desc:** {desc}\n**Details:** {CHAOS_EXAMPLES.get(key, 'See docs')}")
        except Exception as e:
            st.error(f"Error: {e}")

def render_sidebar(ns: str) -> str:
    with st.sidebar:
        st.title("Config")
        ns = st.text_input("Namespace", value=ns)
        model = st.text_input("Ollama Model", value=st.session_state.model)
        base_url = st.text_input("Ollama Base URL", value=st.session_state.base_url)
        st.session_state.model = model.strip() or "qwen:7b"
        st.session_state.base_url = base_url.strip() or "http://localhost:11434"
        
        st.markdown("---")
        st.subheader("Agent")
        
        if not st.session_state.initialized:
            if st.button("Initialize", key="sidebar_initialize", type="primary", use_container_width=True):
                with st.spinner("Initializing..."):
                    if initialize_agent(
                        namespace=ns,
                        model=st.session_state.model,
                        base_url=st.session_state.base_url,
                    ):
                        st.success("Ready!")
                        st.rerun()
        else:
            st.success("Initialized")
            st.caption(f"Model: {st.session_state.model}")
            st.caption(f"Ollama URL: {st.session_state.base_url}")
            if st.session_state.traffic_emulator_started:
                st.caption("Traffic emulator: started on initialize")
            if st.session_state.bootstrap_result:
                with st.expander("Bootstrap details"):
                    st.json(st.session_state.bootstrap_result, expanded=False)
            if st.session_state.ollama_restart_result:
                with st.expander("Ollama restart details"):
                    st.json(st.session_state.ollama_restart_result, expanded=False)
        
        st.markdown("---")
        st.subheader("Actions")

        st.session_state.pod_monitor_auto_refresh = st.toggle(
            "Live Pod Graph (1s)",
            value=st.session_state.pod_monitor_auto_refresh,
            key="sidebar_live_graph_toggle",
            help="When enabled, pod status graph refreshes every second.",
        )

        if st.session_state.initialized and st.button(
            "Start Traffic Emulator",
            key="sidebar_start_traffic",
            use_container_width=True,
        ):
            with st.spinner("Starting in-cluster traffic emulator..."):
                try:
                    result = run_traffic_emulator(
                        namespace=ns,
                        requests_per_service=30,
                        interval_seconds=1,
                        request_timeout_seconds=2,
                    )
                    if result.get("ok"):
                        summary = result.get("traffic_summary", {})
                        st.success(f"Traffic run complete ({summary.get('records', 0)} events)")
                    else:
                        st.error(result.get("error", "Traffic emulator failed"))
                except Exception as e:
                    st.error(f"Error: {e}")
        
        if st.session_state.initialized and st.button("Snapshot", key="sidebar_snapshot"):
            with st.spinner("Fetching..."):
                try:
                    result = get_cluster_snapshot(namespace=ns)
                    st.json(result, expanded=False)
                except Exception as e:
                    st.error(f"Error: {e}")
        
        st.markdown("---")
        st.subheader("Session")
        
        if st.button("Save", key="sidebar_save"):
            fp = st.session_state.memory.save()
            st.success("Saved")
        
        if st.button("Clear", key="sidebar_clear"):
            st.session_state.memory.messages.clear()
            st.session_state.messages = []
            st.success("Cleared")
        
        st.markdown("---")
        st.caption("**H2H CryptoKnights - Phase 6**\nAI K8s Diagnosis & Chaos Testing")
    
    return ns

def cleanup_resources():
    """Cleanup cluster resources on exit."""
    # Note: We use subprocess directly to avoid session state issues in atexit
    ns = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
    try:
        # Just a quick revert to ensure cluster is stable
        subprocess.run(["kubectl", "delete", "-k", "k8s/manifests", "--ignore-not-found=true"], capture_output=True)
    except Exception:
        pass

atexit.register(cleanup_resources)

def main():
    init_session_state()
    
    ns = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
    ns = render_sidebar(ns)
    
    st.title("H2H CryptoKnights: AI K8s Diagnosis")
    st.markdown("*Phase 6: Product Experience - Web Interface*\n\nAI-Powered Kubernetes Troubleshooting & Resilience Testing")
    st.markdown("---")

    render_live_service_stats(ns)
    
    if st.session_state.initialized:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Diagnosis", key="mode_diagnosis", type="primary" if st.session_state.current_mode == "diagnosis" else "secondary", use_container_width=True):
                st.session_state.current_mode = "diagnosis"
                st.rerun()
        with col2:
            if st.button("Chaos", key="mode_chaos", type="primary" if st.session_state.current_mode == "chaos" else "secondary", use_container_width=True):
                st.session_state.current_mode = "chaos"
                st.rerun()
        
        st.markdown("---")
        if st.session_state.current_mode == "diagnosis":
            render_diagnosis_mode(ns)
        else:
            render_chaos_mode(ns)
    else:
        st.info("Click 'Initialize' in sidebar. Requires: Kubernetes cluster + Ollama running")

if __name__ == "__main__":
    main()
