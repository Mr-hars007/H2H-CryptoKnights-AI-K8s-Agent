"""Streamlit UI for H2H CryptoKnights AI K8s Diagnosis Assistant."""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import streamlit as st
from agent import create_agent, ConversationMemory, ConversationState, DiagnosisTraceCallback
from tools import (
    list_scenarios,
    get_cluster_snapshot,
    inject_fault,
    revert_fault,
    list_traces,
)


# Page configuration
st.set_page_config(
    page_title="H2H CryptoKnights - AI K8s Diagnosis",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Styling
st.markdown("""
<style>
    .main {
        padding: 2rem;
    }
    .diagnosis-box {
        background-color: #f0f2f6;
        padding: 1.5rem;
        border-radius: 8px;
        border-left: 4px solid #4CAF50;
        margin: 1rem 0;
    }
    .error-box {
        background-color: #fee;
        padding: 1.5rem;
        border-radius: 8px;
        border-left: 4px solid #ff4444;
        margin: 1rem 0;
    }
    .trace-box {
        background-color: #f5f5f5;
        padding: 1rem;
        border-radius: 4px;
        font-family: monospace;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initialize session state."""
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


def initialize_agent(namespace: str):
    """Initialize the AI agent."""
    try:
        st.session_state.agent = create_agent(namespace=namespace)
        st.session_state.state.namespace = namespace
        st.session_state.initialized = True
        return True
    except Exception as e:
        st.error(f"❌ Failed to initialize agent: {e}")
        st.info("Make sure Ollama is running at http://localhost:11434")
        return False


def render_diagnosis_result(result: dict):
    """Render diagnosis result."""
    if result.get("ok"):
        st.success("✅ Diagnosis complete")
        
        # Main diagnosis
        with st.container():
            st.markdown("### 🔍 Diagnosis Result")
            st.markdown(result.get("diagnosis", "No diagnosis available"))
        
        # Trace information
        if result.get("trace"):
            with st.expander("📋 Reasoning Trace", expanded=False):
                trace_events = result.get("trace", [])
                for i, event in enumerate(trace_events, 1):
                    event_type = event.get("event", "unknown")
                    timestamp = event.get("timestamp", "?")[:19]
                    
                    if event_type == "tool_start":
                        tool = event.get("tool", "?")
                        st.text(f"[{timestamp}] 🔧 Calling tool: {tool}")
                    elif event_type == "agent_action":
                        action = event.get("action", "?")
                        st.text(f"[{timestamp}] ✓ Agent action: {action}")
                    elif event_type == "agent_finish":
                        st.text(f"[{timestamp}] ✅ Diagnosis complete")
    else:
        st.error(f"❌ Diagnosis failed: {result.get('error', 'Unknown error')}")


def main():
    """Main Streamlit app."""
    init_session_state()

    # Header
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("🔍 H2H CryptoKnights: AI K8s Diagnosis")
        st.markdown("*Phase 5: AI Diagnosis Loop - Web Interface*")
    with col2:
        st.image("", use_column_width=True)  # Placeholder for logo

    st.markdown("---")

    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Configuration")
        
        namespace = st.text_input(
            "Kubernetes Namespace",
            value=os.getenv("AI_K8S_NAMESPACE", "ai-ops"),
        )
        
        mode = st.radio(
            "Mode",
            ["Diagnosis", "Chaos Testing"],
            help="Diagnosis: Troubleshoot existing issues | Chaos: Inject faults",
        )
        st.session_state.state.mode = mode.lower()
        
        st.markdown("---")
        
        # Initialize agent button
        if not st.session_state.initialized:
            if st.button("🚀 Initialize Agent", use_container_width=True):
                with st.spinner("Initializing AI agent..."):
                    if initialize_agent(namespace):
                        st.success("✅ Agent ready!")
        else:
            st.success("✅ Agent initialized")
        
        st.markdown("---")
        
        # Quick actions
        st.subheader("Quick Actions")
        
        if st.button("📊 Get Cluster Status", use_container_width=True):
            with st.spinner("Fetching cluster status..."):
                try:
                    result = get_cluster_snapshot(namespace=namespace)
                    st.json(result)
                except Exception as e:
                    st.error(f"Error: {e}")
        
        if st.button("🎯 List Chaos Scenarios", use_container_width=True):
            try:
                scenarios = list_scenarios()
                st.json(scenarios)
            except Exception as e:
                st.error(f"Error: {e}")
        
        st.markdown("---")
        
        # Conversation management
        st.subheader("💾 Conversation")
        if st.button("💾 Save Conversation", use_container_width=True):
            filepath = st.session_state.memory.save()
            st.success(f"Saved to: {filepath}")
        
        if st.button("🗑️ Clear History", use_container_width=True):
            st.session_state.memory.messages.clear()
            st.session_state.messages = []
            st.success("History cleared")


    # Main content area
    if st.session_state.initialized:
        if mode.lower() == "diagnosis":
            render_diagnosis_mode(namespace)
        else:
            render_chaos_mode(namespace)
    else:
        st.info("👈 Please initialize the agent using the sidebar button")


def render_diagnosis_mode(namespace: str):
    """Render diagnosis mode interface."""
    st.header("🔧 Kubernetes Diagnosis")
    
    # Display conversation history
    if st.session_state.messages:
        with st.expander("📝 Conversation History", expanded=False):
            for i, msg in enumerate(st.session_state.messages, 1):
                if msg["role"] == "user":
                    st.write(f"**You ({i}):** {msg['content'][:100]}...")
                else:
                    st.write(f"**Assistant ({i}):** {msg['content'][:100]}...")
    
    st.markdown("---")
    
    # Diagnosis input
    st.subheader("Ask About Cluster Issues")
    
    question = st.text_area(
        "What's wrong with your cluster?",
        placeholder="e.g., 'Why are the orders pods in CrashLoopBackOff?' or 'Why are payments pods pending?'",
        height=100,
    )
    
    col1, col2 = st.columns(2)
    with col1:
        diagnose_clicked = st.button("🔍 Diagnose", use_container_width=True)
    with col2:
        if st.button("📸 Quick Snapshot", use_container_width=True):
            with st.spinner("Collecting cluster evidence..."):
                try:
                    from tools import collect_evidence_snapshot
                    result = collect_evidence_snapshot(namespace=namespace)
                    st.json(result)
                except Exception as e:
                    st.error(f"Error: {e}")
    
    if diagnose_clicked and question:
        st.session_state.messages.append({"role": "user", "content": question})
        
        with st.spinner("🤔 Analyzing cluster (this may take 30-60 seconds)..."):
            try:
                trace_callback = DiagnosisTraceCallback()
                result = st.session_state.agent.diagnose(question, trace_callback=trace_callback)
                
                if result.get("ok"):
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": result.get("diagnosis", ""),
                    })
                
                render_diagnosis_result(result)
            except Exception as e:
                st.error(f"❌ Error during diagnosis: {e}")
                st.error(str(e))


def render_chaos_mode(namespace: str):
    """Render chaos testing mode interface."""
    st.header("⚡ Chaos Testing")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 Available Scenarios")
        try:
            scenarios = list_scenarios()
            selected_scenario = st.selectbox(
                "Choose a scenario to inject:",
                list(scenarios.keys()),
                format_func=lambda x: f"{x}: {scenarios[x]}",
            )
            
            if st.button("💥 Inject Fault", use_container_width=True):
                with st.spinner(f"Injecting {selected_scenario}..."):
                    result = inject_fault(selected_scenario, namespace=namespace)
                    if result.get("ok"):
                        st.success(f"✅ Fault injected: {selected_scenario}")
                    else:
                        st.error(f"Failed to inject fault")
                    st.json(result)
        except Exception as e:
            st.error(f"Error loading scenarios: {e}")
    
    with col2:
        st.subheader("🔄 Fault Management")
        
        if st.button("↩️ Revert All Faults", use_container_width=True):
            with st.spinner("Reverting faults..."):
                try:
                    result = revert_fault(namespace=namespace)
                    if result.get("ok"):
                        st.success("✅ All faults reverted")
                    else:
                        st.error("Failed to revert faults")
                    st.json(result)
                except Exception as e:
                    st.error(f"Error: {e}")
    
    st.markdown("---")
    
    st.info("""
    **Chaos Testing Workflow:**
    1. Select a fault scenario
    2. Click "Inject Fault" to simulate a failure
    3. Use Diagnosis mode to investigate the failure
    4. Click "Revert All Faults" to restore baseline
    """)


if __name__ == "__main__":
    main()

