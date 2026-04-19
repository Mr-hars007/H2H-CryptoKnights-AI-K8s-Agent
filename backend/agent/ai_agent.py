"""Phase 5 AI Diagnosis Agent - ReAct-style Kubernetes troubleshooting assistant."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_ollama import ChatOllama
from langchain.callbacks import BaseCallbackHandler

from .tools import (
    tool_collect_evidence_snapshot,
    tool_get_cluster_status,
    tool_inject_fault_scenario,
    tool_revert_fault,
    tool_list_scenarios,
    tool_monitor_cluster,
)


# Configuration from environment
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")


class DiagnosisTraceCallback(BaseCallbackHandler):
    """Callback handler to collect tool invocations and reasoning traces."""

    def __init__(self):
        self.trace_events: List[Dict[str, Any]] = []
        self.timestamps: Dict[str, str] = {}

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        event = {
            "event": "tool_start",
            "tool": serialized.get("name", "unknown"),
            "input": input_str,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trace_events.append(event)

    def on_tool_end(self, output: str, **kwargs) -> None:
        event = {
            "event": "tool_end",
            "output": output[:500] if len(output) > 500 else output,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trace_events.append(event)

    def on_agent_action(self, action, **kwargs) -> None:
        event = {
            "event": "agent_action",
            "action": action.tool,
            "input": action.tool_input,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trace_events.append(event)

    def on_agent_finish(self, finish, **kwargs) -> None:
        event = {
            "event": "agent_finish",
            "output": finish.return_values.get("output", "")[:300],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.trace_events.append(event)


class KubernetesAIDiagnosisAgent:
    """AI agent for Kubernetes cluster diagnosis and failure analysis."""

    def __init__(
        self,
        namespace: str = DEFAULT_NAMESPACE,
        model: str = OLLAMA_MODEL,
        base_url: str = OLLAMA_BASE_URL,
    ):
        self.namespace = namespace
        self.model_name = model
        self.base_url = base_url

        # Initialize LLM
        self.llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=0.2,
        )

        # Define tools for the agent
        self.tools = self._create_tools()

        # Initialize agent
        self.agent = None
        self.executor = None
        self._initialize_agent()

    def _create_tools(self) -> List[Tool]:
        """Create tool definitions for the agent."""
        return [
            Tool(
                name="collect_evidence",
                func=lambda query: self._tool_collect_evidence(query),
                description=(
                    "Collects comprehensive evidence snapshot from the cluster "
                    "including pod status, logs, events, and deployments. "
                    "Use when you need to investigate cluster state. "
                    "Input: optional comma-separated service list (e.g., 'gateway,orders,payments')"
                ),
            ),
            Tool(
                name="get_cluster_status",
                func=lambda query: self._tool_get_status(query),
                description=(
                    "Quick cluster status check showing pods, services, and recent events. "
                    "Use for rapid health assessment. Input: ignored"
                ),
            ),
            Tool(
                name="list_fault_scenarios",
                func=lambda query: self._tool_list_scenarios(query),
                description=(
                    "List all available chaos injection fault scenarios. "
                    "Use before injecting faults. Input: ignored"
                ),
            ),
            Tool(
                name="inject_fault",
                func=lambda query: self._tool_inject_fault(query),
                description=(
                    "Inject a controlled fault scenario into the cluster for testing. "
                    "Only use in Chaos Mode. Input: scenario key (e.g., 'crashloop_orders')"
                ),
            ),
            Tool(
                name="revert_fault",
                func=lambda query: self._tool_revert_fault(query),
                description=(
                    "Revert all injected faults back to baseline configuration. "
                    "Input: ignored"
                ),
            ),
            Tool(
                name="monitor_health",
                func=lambda query: self._tool_monitor_cluster(query),
                description=(
                    "Monitor cluster health over time with multiple samples. "
                    "Input: comma-separated options (e.g., 'samples=5,interval=10')"
                ),
            ),
        ]

    def _initialize_agent(self) -> None:
        """Initialize the ReAct agent with tools and prompt."""
        prompt_template = """You are an expert Kubernetes troubleshooting assistant. 
Your job is to:
1. Gather evidence about cluster failures using available tools
2. Analyze patterns and symptoms
3. Identify root causes with high confidence
4. Provide actionable remediation steps

Always be thorough: collect multiple pieces of evidence before drawing conclusions.
Explain your reasoning transparently, showing which facts support your diagnosis.

When diagnosing failures:
- Check pod status and restart counts
- Review logs for error patterns
- Examine events for orchestration issues
- Consider resource constraints and configuration mismatches
- Look for cascading failures across services

Format your final answer as:
DIAGNOSIS: [Root cause with confidence level]
SYMPTOMS: [Observable failure signals]
IMPACT: [Which services/users affected]
REMEDIATION: [Step-by-step fix instructions]
VALIDATION: [How to confirm fix worked]

Tools available: {tools}

{format_instructions}

Begin!

Question: {input}

{agent_scratchpad}"""

        prompt = PromptTemplate.from_template(prompt_template)

        # Create ReAct agent
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt,
        )

        # Create executor with tracing
        self.executor = AgentExecutor.from_agent_and_tools(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            max_iterations=15,
            early_stopping_method="generate",
        )

    def _tool_collect_evidence(self, query: str) -> str:
        """Collect evidence snapshot."""
        try:
            services = None
            if query and query.strip():
                services = [s.strip() for s in query.split(",")]
            result = tool_collect_evidence_snapshot(
                namespace=self.namespace,
                services=services,
            )
            return json.dumps(result, indent=2)[:2000]  # Limit output
        except Exception as e:
            return f"Error collecting evidence: {e}"

    def _tool_get_status(self, query: str) -> str:
        """Get quick cluster status."""
        try:
            result = tool_get_cluster_status(namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error getting status: {e}"

    def _tool_list_scenarios(self, query: str) -> str:
        """List available fault scenarios."""
        try:
            result = tool_list_scenarios()
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error listing scenarios: {e}"

    def _tool_inject_fault(self, query: str) -> str:
        """Inject a fault scenario."""
        try:
            scenario = query.strip() if query else None
            if not scenario:
                return "Error: scenario key is required (e.g., 'crashloop_orders')"
            result = tool_inject_fault_scenario(scenario=scenario, namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error injecting fault: {e}"

    def _tool_revert_fault(self, query: str) -> str:
        """Revert all faults."""
        try:
            result = tool_revert_fault(namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error reverting faults: {e}"

    def _tool_monitor_cluster(self, query: str) -> str:
        """Monitor cluster health."""
        try:
            samples = 3
            interval = 10
            if query and query.strip():
                for part in query.split(","):
                    if "samples=" in part:
                        samples = int(part.split("=")[1])
                    elif "interval=" in part:
                        interval = int(part.split("=")[1])
            result = tool_monitor_cluster(
                namespace=self.namespace,
                samples=samples,
                interval_seconds=interval,
            )
            return json.dumps(result, indent=2)[:2000]
        except Exception as e:
            return f"Error monitoring cluster: {e}"

    def diagnose(self, question: str, trace_callback: Optional[DiagnosisTraceCallback] = None) -> Dict[str, Any]:
        """
        Run diagnosis for a given question.

        Args:
            question: Natural language question about cluster failure
            trace_callback: Optional callback to collect execution trace

        Returns:
            Dictionary with diagnosis result and reasoning trace
        """
        callbacks = [trace_callback] if trace_callback else []

        try:
            result = self.executor.invoke(
                {"input": question},
                {"callbacks": callbacks},
            )
            
            return {
                "ok": True,
                "question": question,
                "diagnosis": result.get("output", ""),
                "trace": trace_callback.trace_events if trace_callback else [],
            }
        except Exception as e:
            return {
                "ok": False,
                "question": question,
                "error": str(e),
                "trace": trace_callback.trace_events if trace_callback else [],
            }


def create_agent(namespace: str = DEFAULT_NAMESPACE) -> KubernetesAIDiagnosisAgent:
    """Factory function to create an AI diagnosis agent."""
    return KubernetesAIDiagnosisAgent(namespace=namespace)
