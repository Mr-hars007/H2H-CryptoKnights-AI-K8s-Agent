from __future__ import annotations

import atexit
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from agent import create_agent, ConversationMemory
from tools.k8s_manager import (
    create_pod,
    delete_all,
    delete_pod,
    crashloop_orders,
    get_pod_status,
    initialize_cluster,
    misconfigure_service,
    pause_deployment,
    pending_payments,
    revert,
    start_deployment,
)
from tools.metrics import compute_metrics


def cleanup() -> None:
    delete_all()


atexit.register(cleanup)

st.set_page_config(page_title="ClusterSage", layout="wide")

# Only refresh the dashboard if we are NOT currently analyzing
if "analyzing" not in st.session_state:
    st.session_state.analyzing = False

if not st.session_state.analyzing:
    st_autorefresh(interval=2000, key="dashboard_refresh")

if "agent" not in st.session_state:
    st.session_state.agent = None

if "memory" not in st.session_state:
    st.session_state.memory = ConversationMemory()

if "initialized" not in st.session_state:
    st.session_state.initialized = False

if "metrics_history" not in st.session_state:
    st.session_state.metrics_history = []

if "last_diagnosis" not in st.session_state:
    st.session_state.last_diagnosis = None

if "last_question" not in st.session_state:
    st.session_state.last_question = ""

if "analyzing" not in st.session_state:
    st.session_state.analyzing = False


with st.sidebar:
    st.title("⚙️ Cluster Control")

    model = st.text_input("Model", value="qwen:7b", key="ollama_model")

    if not st.session_state.initialized:
        if st.button("🚀 Initialize Cluster", use_container_width=True):
            output = initialize_cluster()
            st.code(output)
            st.session_state.initialized = True
            st.session_state.agent = create_agent(model=model)
            st.session_state.memory.clear()
            st.session_state.metrics_history = []
            st.success("Cluster initialized")
            st.rerun()
    else:
        st.success("Cluster ready")

    if st.button("🧹 Delete Cluster", use_container_width=True):
        st.code(delete_all())
        st.session_state.initialized = False
        st.session_state.agent = None
        st.session_state.memory.clear()
        st.session_state.metrics_history = []
        st.success("Cluster deleted")
        st.rerun()

    st.divider()
    st.title("💥 Chaos Mode")

    if st.button("CrashLoop Orders", use_container_width=True):
        st.code(crashloop_orders())

    if st.button("Pending Payments", use_container_width=True):
        st.code(pending_payments())

    if st.button("Break Gateway Service", use_container_width=True):
        st.code(misconfigure_service())

    if st.button("♻️ Revert All", use_container_width=True):
        st.code(revert())

    st.divider()
    st.title("🎮 Pod Controls")

    deployment_name = st.selectbox(
        "Deployment",
        ["gateway", "orders", "payments"],
        index=1,
        key="deployment_name",
    )

    if st.button("⏸ Pause Deployment", use_container_width=True):
        st.code(pause_deployment(deployment_name))

    if st.button("▶ Start Deployment", use_container_width=True):
        st.code(start_deployment(deployment_name, replicas=1))

    st.caption("Create/Delete work on plain pods in the ai-ops namespace.")
    pod_name = st.text_input("Pod name", value="test-pod", key="pod_name")

    if st.button("➕ Create Pod", use_container_width=True):
        st.code(create_pod(pod_name))

    delete_name = st.text_input("Delete pod name", value="", key="delete_pod_name")

    if st.button("🗑 Delete Pod", use_container_width=True):
        if delete_name.strip():
            st.code(delete_pod(delete_name.strip()))
        else:
            st.warning("Enter a pod name first.")


st.title("ClusterSage")

if not st.session_state.initialized:
    st.info("Click Initialize in the sidebar.")
    st.stop()

st.caption("Auto refresh is on. The dashboard updates every 2 seconds.")

pods = get_pod_status()
metrics = compute_metrics(pods)

now = time.time()
if not st.session_state.metrics_history or now - st.session_state.metrics_history[-1]["time"] >= 1.5:
    st.session_state.metrics_history.append(
        {
            "time": now,
            "latency": metrics["latency"],
            "error_rate": metrics["error_rate"],
        }
    )

st.session_state.metrics_history = [
    item for item in st.session_state.metrics_history if now - item["time"] <= 60
]

top1, top2, top3, top4 = st.columns(4)
top1.metric("Latency (ms)", metrics["latency"])
top2.metric("Error Rate (%)", metrics["error_rate"])
top3.metric("Active Pods", metrics.get("active", 0))
top4.metric("Crashed / Not Ready", metrics.get("crashed", 0))

st.markdown("## 📊 Live Cluster Dashboard")

running = [p for p in pods if str(p["status"]).lower() == "running"]
starting = [p for p in pods if str(p["status"]).lower() in {"pending", "containercreating"}]
failed = [p for p in pods if str(p["status"]).lower() not in {"running", "pending", "containercreating"}]

c1, c2, c3 = st.columns(3)
c1.success(f"Active: {len(running)}")
c2.info(f"Starting / Inactive: {len(starting)}")
c3.error(f"Crashed / Failed: {len(failed)}")

st.markdown("### Pod Status")

for pod in pods:
    status = str(pod["status"])
    name = str(pod["name"])

    if status.lower() == "running":
        st.success(f"{name} - {status}")
    elif status.lower() in {"pending", "containercreating"}:
        st.info(f"{name} - {status}")
    else:
        st.error(f"{name} - {status}")

history_df = pd.DataFrame(st.session_state.metrics_history)
if not history_df.empty:
    history_df["time"] = pd.to_datetime(history_df["time"], unit="s")
    history_df = history_df.set_index("time").sort_index()

    st.markdown("### Metrics Over Time")
    st.line_chart(history_df[["latency", "error_rate"]])

st.markdown("## 🤖 Diagnosis")

col1, col2, col3 = st.columns([3, 1, 1])
with col2:
    auto_refresh_diagnosis = st.checkbox("Auto-refresh", value=False, help="Re-run diagnosis every 10 seconds")
with col3:
    if st.button("🧹 Clear", use_container_width=True):
        st.session_state.last_diagnosis = None
        st.session_state.last_question = ""
        st.rerun()

question = st.text_area(
    "Ask your question:",
    placeholder="Why is my e-commerce software not working?",
    height=120,
    key="question_input",
)

if st.button("Analyze", use_container_width=True, disabled=st.session_state.analyzing) and question.strip():
    st.session_state.analyzing = True
    st.session_state.last_question = question.strip()
    st.rerun()

if st.session_state.analyzing:
    agent = st.session_state.agent
    if agent is None:
        st.error("Agent is not initialized.")
        st.session_state.analyzing = False
        st.rerun()
    else:
        # Create a placeholder for the streaming response
        st.markdown("### 🤖 AI Diagnosis in Progress...")
        response_placeholder = st.empty()
        
        # Use stream_run
        full_diagnosis = ""
        context_data = {}
        
        for update in agent.stream_run(st.session_state.last_question):
            if not update.get("ok", True):
                st.error(update.get("error", "Unknown error during streaming"))
                st.session_state.analyzing = False
                st.rerun()
                
            utype = update.get("type")
            if utype == "context":
                context_data = update
            elif utype == "chunk":
                full_diagnosis += update.get("content", "")
                response_placeholder.markdown(full_diagnosis + "▌")
            elif utype == "final":
                # Final cleanup and storage
                response_placeholder.markdown(update.get("diagnosis", ""))
                st.session_state.last_diagnosis = update
                st.session_state.last_diagnosis_time = time.time()
                st.session_state.memory.add_user_message(st.session_state.last_question)
                st.session_state.memory.add_assistant_message(update.get("diagnosis", ""))
                st.session_state.analyzing = False
                st.rerun()

# Auto-refresh diagnosis if enabled (only when not already analyzing)
if auto_refresh_diagnosis and st.session_state.last_question and st.session_state.agent and not st.session_state.analyzing:
    if "last_diagnosis_time" not in st.session_state:
        st.session_state.last_diagnosis_time = 0
    
    current_time = time.time()
    if current_time - st.session_state.last_diagnosis_time >= 15: # 15s for auto-refresh
        st.session_state.analyzing = True
        st.rerun()

# Display the last diagnosis if it exists
if st.session_state.last_diagnosis:
    result = st.session_state.last_diagnosis
    
    # Show when diagnosis was run
    if "last_diagnosis_time" in st.session_state and st.session_state.last_diagnosis_time > 0:
        diagnosis_age = int(time.time() - st.session_state.last_diagnosis_time)
        st.caption(f"Last diagnosis: {diagnosis_age}s ago")
    
    if result.get("ok"):
        # Show health status badge
        is_healthy = result.get("is_healthy", False)
        if is_healthy:
            st.success("🟢 CLUSTER HEALTHY")
        else:
            st.error("🔴 CLUSTER DEGRADED")
        
        answer = str(result.get("diagnosis", "")).strip()
        st.markdown(answer)

        st.markdown("## 📦 Pods")
        st.code(str(result.get("pods", "")), language="text")

        st.markdown("## 📜 Logs")
        logs_text = str(result.get("logs", "")).strip()
        if logs_text:
            with st.expander("View Full Logs and Diagnostics", expanded=False):
                st.code(logs_text, language="text")
        else:
            st.info("✅ No issues - logs not collected (cluster is healthy)")
    else:
        st.error(str(result.get("error", "Unknown error")))

st.markdown("---")
st.subheader("Conversation")

for message in st.session_state.memory.history:
    role = str(message.get("role", "")).capitalize()
    content = str(message.get("content", ""))
    st.write(f"**{role}:** {content}")