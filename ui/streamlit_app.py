from __future__ import annotations

import os
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import streamlit as st
from agent import create_agent, ConversationMemory, ConversationState, DiagnosisTraceCallback
from tools import list_scenarios, get_cluster_snapshot, inject_fault, revert_fault

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

def initialize_agent(namespace: str) -> bool:
    try:
        st.session_state.agent = create_agent(namespace=namespace)
        st.session_state.state.namespace = namespace
        st.session_state.initialized = True
        return True
    except Exception as e:
        st.error(f"Failed: {str(e)}")
        st.info("Make sure Ollama is running: ollama serve")
        return False

def render_diagnosis_result(result: dict):
    if result.get("ok"):
        st.success("Diagnosis Complete")
        st.markdown(f"### Analysis\n{result.get('diagnosis', 'No diagnosis')}")
        if result.get("trace"):
            with st.expander("Trace"):
                for event in result.get("trace", []):
                    if event.get("event") == "tool_start":
                        st.text(f"Tool: {event.get('tool', '?')}")
    else:
        st.error(f"Failed: {result.get('error', 'Unknown error')}")

def render_diagnosis_mode(ns: str):
    col1, col2 = st.columns([2, 1])
    with col1:
        st.header("Kubernetes Diagnosis")
    with col2:
        if st.button("Refresh"):
            st.rerun()
    
    st.markdown("---")
    tab1, tab2, tab3 = st.tabs(["Diagnosis", "Status", "History"])
    
    with tab1:
        selected = st.selectbox("Template:", ["Custom"] + list(DIAGNOSTIC_TEMPLATES.keys()))
        if selected != "Custom":
            st.info(f"Template: {DIAGNOSTIC_TEMPLATES[selected]}")
        
        question = st.text_area("What's wrong?", placeholder="e.g., Why are orders pods failing?", height=100)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Analyze", type="primary", use_container_width=True) and question:
                st.session_state.messages.append({"role": "user", "content": question})
                with st.spinner("Analyzing (30-60s)..."):
                    try:
                        result = st.session_state.agent.diagnose(question, trace_callback=DiagnosisTraceCallback())
                        if result.get("ok"):
                            st.session_state.messages.append({"role": "assistant", "content": result.get("diagnosis", "")})
                        render_diagnosis_result(result)
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
        with col2:
            if st.button("Snapshot"):
                with st.spinner("Fetching..."):
                    try:
                        result = get_cluster_snapshot(namespace=ns)
                        st.json(result, expanded=False)
                    except Exception as e:
                        st.error(f"Error: {e}")
        with col3:
            if st.button("Help"):
                st.info("Be specific about failing service. Include symptoms like CrashLoopBackOff or Pending.")
    
    with tab2:
        if st.button("Fetch Status"):
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
    
    with tab3:
        if st.session_state.messages:
            for i, msg in enumerate(st.session_state.messages, 1):
                icon = "User" if msg["role"] == "user" else "Assistant"
                st.write(f"**{icon} {msg['role'].title()} ({i}):** {msg['content'][:100]}...")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save"):
                    fp = st.session_state.memory.save()
                    st.success(f"Saved: {Path(fp).name}")
            with col2:
                if st.button("Clear"):
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
        if st.button("Refresh"):
            st.rerun()
    
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
                
                if st.button("Inject", type="primary", use_container_width=True):
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
            if st.button("Revert All", type="primary", use_container_width=True):
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
            if st.button("State", use_container_width=True):
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
        
        st.markdown("---")
        st.subheader("Agent")
        
        if not st.session_state.initialized:
            if st.button("Initialize", type="primary", use_container_width=True):
                with st.spinner("Initializing..."):
                    if initialize_agent(ns):
                        st.success("Ready!")
                        st.rerun()
        else:
            st.success("Initialized")
        
        st.markdown("---")
        st.subheader("Actions")
        
        if st.session_state.initialized and st.button("Snapshot"):
            with st.spinner("Fetching..."):
                try:
                    result = get_cluster_snapshot(namespace=ns)
                    st.json(result, expanded=False)
                except Exception as e:
                    st.error(f"Error: {e}")
        
        st.markdown("---")
        st.subheader("Session")
        
        if st.button("Save"):
            fp = st.session_state.memory.save()
            st.success("Saved")
        
        if st.button("Clear"):
            st.session_state.memory.messages.clear()
            st.session_state.messages = []
            st.success("Cleared")
        
        st.markdown("---")
        st.caption("**H2H CryptoKnights - Phase 6**\nAI K8s Diagnosis & Chaos Testing")
    
    return ns

def main():
    init_session_state()
    
    ns = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
    ns = render_sidebar(ns)
    
    st.title("H2H CryptoKnights: AI K8s Diagnosis")
    st.markdown("*Phase 6: Product Experience - Web Interface*\n\nAI-Powered Kubernetes Troubleshooting & Resilience Testing")
    st.markdown("---")
    
    if st.session_state.initialized:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Diagnosis", type="primary" if st.session_state.current_mode == "diagnosis" else "secondary", use_container_width=True):
                st.session_state.current_mode = "diagnosis"
                st.rerun()
        with col2:
            if st.button("Chaos", type="primary" if st.session_state.current_mode == "chaos" else "secondary", use_container_width=True):
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
