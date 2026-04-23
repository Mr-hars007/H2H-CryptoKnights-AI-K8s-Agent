from __future__ import annotations

import sys
from pathlib import Path
import atexit
import time

# ✅ MUST COME FIRST
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import streamlit as st
import pandas as pd

from agent import create_agent, ConversationMemory
from tools.k8s_manager import (
    initialize_cluster,
    delete_all,
    crashloop_orders,
    pending_payments,
    misconfigure_service,
    revert,
    get_pod_status,
    run
)
from tools.metrics import compute_metrics

# ---------------- CLEANUP ----------------

def cleanup():
    delete_all()

atexit.register(cleanup)

# ---------------- CONFIG ----------------

st.set_page_config(page_title="AI K8s Diagnosis", layout="wide")

# ---------------- SESSION INIT ----------------

if "agent" not in st.session_state:
    st.session_state.agent = None

if "memory" not in st.session_state:
    st.session_state.memory = ConversationMemory()

if "initialized" not in st.session_state:
    st.session_state.initialized = False

# ---------------- SIDEBAR ----------------

with st.sidebar:
    st.title("⚙️ Cluster Control")

    if st.button("🚀 Initialize Cluster"):
        st.code(initialize_cluster())
        st.session_state.initialized = True
        st.session_state.agent = create_agent(model="qwen:7b")
        st.success("Cluster initialized")
        st.rerun()

    if st.button("🧹 Delete Cluster"):
        st.code(delete_all())
        st.session_state.initialized = False
        st.session_state.agent = None
        st.success("Cluster deleted")
        st.rerun()

    st.divider()

    st.title("💥 Chaos Mode")

    if st.button("CrashLoop Orders"):
        st.code(crashloop_orders())

    if st.button("Pending Payments"):
        st.code(pending_payments())

    if st.button("Break Gateway Service"):
        st.code(misconfigure_service())

    if st.button("♻️ Revert All"):
        st.code(revert())

# ---------------- MAIN ----------------

st.title("🔥 AI Kubernetes Diagnosis")

if not st.session_state.initialized:
    st.info("Click Initialize in sidebar")
    st.stop()

# ---------------- LIVE DASHBOARD ----------------

st.markdown("## 📊 Live Cluster Dashboard")

pods = get_pod_status()
metrics = compute_metrics(pods)

col1, col2, col3 = st.columns(3)

col1.metric("Latency (ms)", metrics["latency"])
col2.metric("Error Rate (%)", metrics["error_rate"])
col3.metric("Throughput", metrics["throughput"])

st.markdown("### Pod Status")

for p in pods:
    if p["status"] == "Running":
        st.success(f"{p['name']} - Running")
    elif "Crash" in p["status"]:
        st.error(f"{p['name']} - {p['status']}")
    else:
        st.warning(f"{p['name']} - {p['status']}")

st.line_chart([metrics["latency"], metrics["error_rate"]])

# ---------------- CONTROL ----------------

st.markdown("## 🎮 Pod Controls")

if st.button("➕ Create Pod"):
    st.code(run(["kubectl", "run", "test-pod", "--image=nginx", "-n", "ai-ops"]))

if st.button("⛔ Stop Orders"):
    st.code(run(["kubectl", "scale", "deployment/orders", "--replicas=0", "-n", "ai-ops"]))

if st.button("▶ Start Orders"):
    st.code(run(["kubectl", "scale", "deployment/orders", "--replicas=1", "-n", "ai-ops"]))

# ---------------- CHAT ----------------

st.markdown("## 🤖 Diagnosis")

question = st.text_area("Ask your question:")

if st.button("Analyze") and question:
    agent = st.session_state.agent
    memory = st.session_state.memory

    context = ""
    for role, msg in memory.history[-6:]:
        context += f"{role}: {msg}\n"

    prompt = f"{context}\nUser: {question}"

    with st.spinner("Thinking..."):
        result = agent.run(prompt)

    st.write("DEBUG:", result)

    if result.get("ok"):
        answer = result["diagnosis"]

        memory.history.append(("User", question))
        memory.history.append(("Assistant", answer))

        st.success(answer)

        st.markdown("## 📦 Pods")
        st.code(result.get("pods", ""))

        st.markdown("## 📜 Logs")
        st.code(result.get("logs", ""))

    else:
        st.error(result.get("error"))

# ---------------- HISTORY ----------------

st.markdown("---")
st.subheader("Conversation")

for role, msg in st.session_state.memory.history:
    st.write(f"**{role}:** {msg}")

# ---------------- AUTO REFRESH ----------------

time.sleep(1)
st.rerun()