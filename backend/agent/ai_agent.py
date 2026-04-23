"""Phase 5 AI Diagnosis Agent - ReAct-style Kubernetes troubleshooting assistant."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

try:
    from langchain.agents import Tool, AgentExecutor, create_react_agent
    from langchain.prompts import PromptTemplate
    from langchain_ollama import ChatOllama
    try:
        from langchain.callbacks.base import BaseCallbackHandler
    except ImportError:
        from langchain_core.callbacks.base import BaseCallbackHandler
    HAS_LANGCHAIN = True
except ImportError:
    Tool = Any
    AgentExecutor = None
    create_react_agent = None
    PromptTemplate = None
    ChatOllama = None

    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass

    HAS_LANGCHAIN = False

from .tools import (
    tool_collect_evidence_snapshot,
    tool_discover_services,
    tool_generate_live_traffic,
    tool_get_cluster_status,
    tool_inject_fault_scenario,
    tool_revert_fault,
    tool_list_scenarios,
    tool_monitor_cluster,
)


UNHEALTHY_POD_STATUSES = {
    "crashloopbackoff",
    "error",
    "oomkilled",
    "pending",
    "imagepullbackoff",
    "errimagepull",
    "createcontainerconfigerror",
    "createcontainererror",
    "runcontainererror",
    "containercreating",
}

ROOT_CAUSE_HINTS = [
    ("oomkilled", "container was OOMKilled"),
    ("back-off restarting failed container", "container is crash-looping"),
    ("crashloopbackoff", "container is crash-looping"),
    ("error: unknown flag", "container command or arguments are invalid"),
    ("flag provided but not defined", "container command or arguments are invalid"),
    ("exit code", "container exited with a non-zero code"),
    ("failed to start", "application failed during startup"),
    ("failedscheduling", "pod cannot be scheduled"),
    ("insufficient memory", "cluster does not have enough memory for the pod"),
    ("insufficient cpu", "cluster does not have enough CPU for the pod"),
    ("connection refused", "application dependency is refusing connections"),
    ("no endpoints available", "service has no healthy endpoints"),
    ("endpoints", "service endpoints look unhealthy"),
    ("target port", "service port mapping may be wrong"),
    ("targetport", "service port mapping may be wrong"),
    ("readiness probe failed", "readiness checks are failing"),
    ("liveness probe failed", "liveness checks are failing"),
]

KNOWN_DEMO_SERVICES = ["gateway", "orders", "payments"]


def _parse_table_rows(table_stdout: str) -> List[List[str]]:
    rows: List[List[str]] = []
    for raw_line in (table_stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if not parts or parts[0].lower() == "name":
            continue
        rows.append(parts)
    return rows


def _parse_pods_table(table_stdout: str) -> List[Dict[str, str]]:
    pods: List[Dict[str, str]] = []
    for parts in _parse_table_rows(table_stdout):
        if len(parts) < 5:
            continue
        pods.append(
            {
                "name": parts[0],
                "ready": parts[1],
                "status": parts[2],
                "restarts": parts[3],
                "age": parts[4],
            }
        )
    return pods


def _extract_step_stdout(payload: Dict[str, Any], command_fragment: str) -> str:
    if not isinstance(payload, dict):
        return ""
    for step in payload.get("steps", []):
        command = str(step.get("command", "") or "").lower()
        if command_fragment in command:
            return str(step.get("stdout", "") or "")
    return ""


def _collect_signal_lines(step: Dict[str, Any]) -> List[str]:
    signal_lines = step.get("signal_lines")
    if isinstance(signal_lines, list):
        return [str(line) for line in signal_lines if str(line).strip()]
    stdout = str(step.get("stdout", "") or "")
    return [line.strip() for line in stdout.splitlines() if line.strip()][-8:]


def _service_from_pod_name(pod_name: str, known_services: List[str]) -> str:
    for service in known_services:
        if pod_name == service or pod_name.startswith(f"{service}-"):
            return service
    return pod_name.split("-", 1)[0] if "-" in pod_name else pod_name


def _extract_question_services(question: str, known_services: List[str]) -> List[str]:
    lowered = (question or "").lower()
    candidates = known_services or KNOWN_DEMO_SERVICES
    return [service for service in candidates if service in lowered]


def _extract_root_cause_hint(lines: List[str]) -> Optional[str]:
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("targetport:") or lowered.startswith("target port:"):
            continue
        for token, hint in ROOT_CAUSE_HINTS:
            if token in lowered:
                return f"{hint}: {line.strip()}"
    return lines[0].strip() if lines else None


def _build_live_diagnosis(
    namespace: str,
    question: str,
    status_snapshot: Dict[str, Any],
    evidence_snapshot: Dict[str, Any],
) -> Dict[str, str]:
    services = list(evidence_snapshot.get("services", []) if isinstance(evidence_snapshot, dict) else [])
    pods_stdout = _extract_step_stdout(status_snapshot, " get pods")
    event_stdout = _extract_step_stdout(status_snapshot, " get events")
    pod_rows = _parse_pods_table(pods_stdout)
    event_lines = [line.strip() for line in (event_stdout or "").splitlines() if line.strip()]
    lower_question = question.lower()

    unhealthy_pods = []
    for pod in pod_rows:
        status = (pod.get("status") or "").lower()
        restarts = str(pod.get("restarts", "0"))
        restart_count = int(restarts) if restarts.isdigit() else 0
        if status in UNHEALTHY_POD_STATUSES or restart_count > 0 or status != "running":
            unhealthy_pods.append(pod)

    mentioned_services = _extract_question_services(question, services or KNOWN_DEMO_SERVICES)
    targeted_service = mentioned_services[0] if mentioned_services else None

    service_evidence = evidence_snapshot.get("service_evidence", {}) if isinstance(evidence_snapshot, dict) else {}
    findings: List[str] = []

    def service_log_signals(service_name: str) -> List[str]:
        service_payload = service_evidence.get(service_name, {}) if isinstance(service_evidence, dict) else {}
        pods = service_payload.get("pods", {}) if isinstance(service_payload, dict) else {}
        lines: List[str] = []
        for pod_payload in pods.values():
            if not isinstance(pod_payload, dict):
                continue
            for step in pod_payload.get("steps", []):
                command = str(step.get("command", "") or "").lower()
                if " logs " in command or command.endswith(" logs"):
                    lines.extend(_collect_signal_lines(step))
        return lines

    def service_log_excerpt(service_name: str) -> str:
        for line in service_log_signals(service_name):
            cleaned = line.strip()
            if cleaned:
                return cleaned
        return ""

    def service_step_signals(service_name: str) -> List[str]:
        service_payload = service_evidence.get(service_name, {}) if isinstance(service_evidence, dict) else {}
        lines: List[str] = []
        for step in service_payload.get("steps", []) if isinstance(service_payload, dict) else []:
            lines.extend(_collect_signal_lines(step))
        return lines

    selected_pods = unhealthy_pods
    if targeted_service:
        targeted_pods = [
            pod for pod in unhealthy_pods
            if _service_from_pod_name(str(pod.get("name", "")), services) == targeted_service
        ]
        if targeted_pods:
            selected_pods = targeted_pods

    if selected_pods:
        primary = selected_pods[0]
        pod_name = str(primary.get("name", "unknown"))
        pod_status = str(primary.get("status", "unknown"))
        service_name = _service_from_pod_name(pod_name, services)
        pod_and_event_lines = service_log_signals(service_name) + event_lines[-20:]
        related_lines = pod_and_event_lines
        if pod_status.lower() in {"running"} and not related_lines:
            related_lines = service_step_signals(service_name)
        hint = _extract_root_cause_hint(related_lines)
        log_excerpt = service_log_excerpt(service_name)

        if pod_status.lower() == "pending":
            diagnosis = f"The {service_name} workload is unhealthy because pod `{pod_name}` is stuck in Pending."
            symptom = f"`{pod_name}` is `Pending` in namespace `{namespace}`."
            remediation = "Check recent scheduling events, then reduce resource requests or free cluster capacity before retrying."
        elif pod_status.lower() in {"crashloopbackoff", "error"} or str(primary.get("restarts", "0")) not in {"0", ""}:
            diagnosis = f"The {service_name} workload is unhealthy because pod `{pod_name}` is repeatedly failing and restarting."
            symptom = f"`{pod_name}` is `{pod_status}` with {primary.get('restarts', '0')} restarts."
            remediation = "Open the failing pod logs and recent events, then fix the startup/configuration issue causing the container to exit."
        elif pod_status.lower() == "oomkilled":
            diagnosis = f"The {service_name} workload is unhealthy because pod `{pod_name}` was OOMKilled."
            symptom = f"`{pod_name}` shows `OOMKilled` behavior."
            remediation = "Increase memory limits or reduce memory usage, then restart the deployment and confirm the pod stays Ready."
        else:
            diagnosis = f"The {service_name} workload is unhealthy because pod `{pod_name}` is not healthy."
            symptom = f"`{pod_name}` is reporting `{pod_status}`."
            remediation = "Inspect the pod logs and events for the failing workload, then correct the underlying deployment or service issue."

        if hint:
            diagnosis = f"{diagnosis} Most likely cause from live evidence: {hint}"

        impact = f"The `{service_name}` service in namespace `{namespace}` is degraded or unavailable."
        findings.append(f"Affected pod: {pod_name}")
        if hint:
            findings.append(f"Evidence: {hint}")
        if log_excerpt:
            findings.append(f"Log: {log_excerpt}")
        return {
            "diagnosis": diagnosis,
            "symptom": symptom,
            "impact": impact,
            "remediation": remediation,
            "validation": f"Re-run `kubectl get pods -n {namespace}` and confirm `{pod_name}` reaches `Running`/`Ready` with no fresh warning events.",
            "evidence": " | ".join(findings),
        }

    if targeted_service:
        related_lines = service_log_signals(targeted_service) + event_lines[-20:] + service_step_signals(targeted_service)
        hint = _extract_root_cause_hint(related_lines)
        log_excerpt = service_log_excerpt(targeted_service)
        diagnosis = f"The `{targeted_service}` service is the most likely affected workload in namespace `{namespace}`."
        if hint:
            diagnosis = f"{diagnosis} Most likely cause from live evidence: {hint}"
        return {
            "diagnosis": diagnosis,
            "symptom": f"Question targets `{targeted_service}`, but pod-level failure status was not explicit in the quick snapshot.",
            "impact": f"The `{targeted_service}` path may be degraded for users of the demo stack.",
            "remediation": "Inspect service selectors, endpoints, recent events, and pod logs for the targeted workload.",
            "validation": f"Confirm `{targeted_service}` pods stay Ready and the service responds normally after the fix.",
            "evidence": " | ".join(
                item for item in [hint, f"Log: {log_excerpt}" if log_excerpt else ""] if item
            ) or "No explicit unhealthy pod was found in the quick snapshot.",
        }

    healthy_count = sum(1 for pod in pod_rows if (pod.get("status") or "").lower() == "running")
    return {
        "diagnosis": f"The cluster snapshot does not show a clear failing workload right now in namespace `{namespace}`.",
        "symptom": f"{healthy_count} pods are currently `Running`; no obvious unhealthy pod was detected in the latest quick snapshot.",
        "impact": f"No single broken workload could be confirmed from live evidence in namespace `{namespace}`.",
        "remediation": "Run diagnosis again during the failure window or inspect the service-specific logs and events for intermittent issues.",
        "validation": "Verify the reported issue reproduces and check for fresh warning events or non-Running pods.",
        "evidence": "Quick snapshot looked healthy.",
    }


# Configuration from environment
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")
DEFAULT_NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "90"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))
DIAGNOSIS_TIMEOUT_SECONDS = int(os.getenv("DIAGNOSIS_TIMEOUT_SECONDS", "120"))


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
        self.llm = None
        self.tools: List[Tool] = []
        self.agent = None
        self.executor = None
        self.fallback_mode = not HAS_LANGCHAIN
        self._tool_calls_used = 0

        if HAS_LANGCHAIN:
            # Initialize LLM
            self.llm = ChatOllama(
                model=model,
                base_url=base_url,
                temperature=0.2,
                timeout=OLLAMA_TIMEOUT_SECONDS,
                num_predict=OLLAMA_NUM_PREDICT,
                streaming=True,
            )

            # Define tools for the agent
            self.tools = self._create_tools()

            # Initialize agent
            self._initialize_agent()

    def _create_tools(self) -> List[Tool]:
        """Create tool definitions for the agent."""
        return [
            Tool(
                name="collect_evidence",
                func=lambda query: self._tool_collect_evidence(query),
                description=(
                    "CRITICAL: Use this for deep investigation. Collects logs, events, and status. "
                    "Input: Comma-separated service names (e.g., 'gateway,orders') or 'all' to check everything."
                ),
            ),
            Tool(
                name="get_cluster_status",
                func=lambda query: self._tool_get_status(query),
                description=(
                    "Use for a quick overview of pod states and recent events in the namespace. "
                    "Input: Just the namespace name or 'current'."
                ),
            ),
            Tool(
                name="discover_services",
                func=lambda query: self._tool_discover_services(query),
                description=(
                    "Identifies which microservices are currently running. "
                    "Use this first if you don't know the service names. Input: 'none'."
                ),
            ),
            Tool(
                name="list_fault_scenarios",
                func=lambda query: self._tool_list_scenarios(query),
                description="Lists available chaos tests. Input: 'none'.",
            ),
            Tool(
                name="inject_fault",
                func=lambda query: self._tool_inject_fault(query),
                description="Injects a specific chaos fault. Input: Scenario key (e.g., 'crashloop_orders').",
            ),
            Tool(
                name="revert_fault",
                func=lambda query: self._tool_revert_fault(query),
                description="Restores cluster to healthy state. Input: 'none'.",
            ),
        ]

    def _initialize_agent(self) -> None:
        """Initialize the ReAct agent with tools and prompt."""
        if not HAS_LANGCHAIN:
            return

        prompt_template = """You are the H2H-CryptoKnights AI K8s Specialist.
Your mission: Diagnose and fix Kubernetes failures with absolute precision and speed.

CRITICAL CONSTRAINTS:
1. Start your Final Answer exactly as the user requested (e.g., if they say "start with cat", you MUST start with "cat").
2. Keep your Final Answer CONCISE (under 150 words).
3. Do not hallucinate tools. Use ONLY: [{tool_names}].
4. If you see CrashLoopBackOff or Error, you MUST call 'collect_evidence' for that service to see the logs.
5. Your diagnosis must be based on LIVE evidence, not assumptions.

DIAGNOSIS PROTOCOL:
- Step 1: Discover services if unknown.
- Step 2: Get cluster status to identify failing pods.
- Step 3: Collect evidence (logs/events) for the failing workloads.
- Step 4: Synthesize a Final Answer (Ground truth only).

Format your Final Answer like this:
[User's requested start word, if any]
DIAGNOSIS: <Root cause>
SYMPTOMS: <Observed signals>
REMEDIATION: <Fix steps>

Tools: {tools}

Use this format:
Thought: What am I looking for?
Action: The tool to use (must be one of [{tool_names}])
Action Input: The specific input for the tool
Observation: Result from the tool
... (repeat as needed)
Thought: I have sufficient evidence.
Final Answer: [Your response under 150 words starting with the user's requested word]

Begin!

Question: {input}
{agent_scratchpad}"""

        prompt = PromptTemplate.from_template(prompt_template)

        self.agent = create_react_agent(llm=self.llm, tools=self.tools, prompt=prompt)

        self.executor = AgentExecutor.from_agent_and_tools(
            agent=self.agent,
            tools=self.tools,
            verbose=False,
            max_iterations=8,
            early_stopping_method="force",
            handle_parsing_errors=True,
        )

    def _tool_collect_evidence(self, query: str) -> str:
        """Collect evidence snapshot."""
        allowed, message = self._allow_tool_call("collect_evidence")
        if not allowed:
            return message
        try:
            services = None
            if query and query.strip():
                services = [s.strip() for s in query.split(",")]
            result = tool_collect_evidence_snapshot(
                namespace=self.namespace,
                services=services,
                log_tail_lines=60,
                include_describe=False,
            )
            return json.dumps(result, indent=2)[:2000]  # Limit output
        except Exception as e:
            return f"Error collecting evidence: {e}"

    def _tool_get_status(self, query: str) -> str:
        """Get quick cluster status."""
        allowed, message = self._allow_tool_call("get_cluster_status")
        if not allowed:
            return message
        try:
            result = tool_get_cluster_status(namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error getting status: {e}"

    def _tool_discover_services(self, query: str) -> str:
        """Discover live namespace services."""
        allowed, message = self._allow_tool_call("discover_services")
        if not allowed:
            return message
        try:
            result = tool_discover_services(namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error discovering services: {e}"

    def _tool_list_scenarios(self, query: str) -> str:
        """List available fault scenarios."""
        allowed, message = self._allow_tool_call("list_fault_scenarios")
        if not allowed:
            return message
        try:
            result = tool_list_scenarios()
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error listing scenarios: {e}"

    def _tool_inject_fault(self, query: str) -> str:
        """Inject a fault scenario."""
        allowed, message = self._allow_tool_call("inject_fault")
        if not allowed:
            return message
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
        allowed, message = self._allow_tool_call("revert_fault")
        if not allowed:
            return message
        try:
            result = tool_revert_fault(namespace=self.namespace)
            return json.dumps(result, indent=2)[:1500]
        except Exception as e:
            return f"Error reverting faults: {e}"

    def _tool_monitor_cluster(self, query: str) -> str:
        """Monitor cluster health."""
        allowed, message = self._allow_tool_call("monitor_health")
        if not allowed:
            return message
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

    def _tool_generate_traffic(self, query: str) -> str:
        """Generate real traffic to live services."""
        allowed, message = self._allow_tool_call("generate_live_traffic")
        if not allowed:
            return message
        try:
            services = None
            requests_per_service = 20
            interval_seconds = 1
            request_timeout_seconds = 2

            if query and query.strip():
                for raw_part in query.split(","):
                    part = raw_part.strip()
                    if not part or "=" not in part:
                        continue

                    key, value = [token.strip() for token in part.split("=", 1)]
                    if key == "services" and value:
                        services = [item.strip() for item in value.split("|") if item.strip()]
                    elif key == "requests" and value:
                        requests_per_service = int(value)
                    elif key == "interval" and value:
                        interval_seconds = int(value)
                    elif key == "timeout" and value:
                        request_timeout_seconds = int(value)

            result = tool_generate_live_traffic(
                namespace=self.namespace,
                services=services,
                requests_per_service=requests_per_service,
                interval_seconds=interval_seconds,
                request_timeout_seconds=request_timeout_seconds,
            )
            return json.dumps(result, indent=2)[:4000]
        except Exception as e:
            return f"Error generating live traffic: {e}"

    def _allow_tool_call(self, tool_name: str) -> tuple[bool, str]:
        """Allow sufficient tool calls for deep diagnosis."""
        if self._tool_calls_used >= 10:
            return (
                False,
                (
                    "Tool usage limit reached (max 10). "
                    "Please provide a Final Answer now based on collected evidence."
                ),
            )
        self._tool_calls_used += 1
        return True, ""

    def diagnose(
        self,
        question: str,
        trace_callback: Optional[DiagnosisTraceCallback] = None,
        thread_initializer: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Run diagnosis for a given question.

        Args:
            question: Natural language question about cluster failure
            trace_callback: Optional callback to collect execution trace
            thread_initializer: Optional function to initialize background threads (e.g. for Streamlit context)

        Returns:
            Dictionary with diagnosis result and reasoning trace
        """
        if not HAS_LANGCHAIN:
            return self._fallback_diagnose(question, trace_callback=trace_callback)

        callbacks = [trace_callback] if trace_callback else []
        self._tool_calls_used = 0

        try:
            with ThreadPoolExecutor(max_workers=1, initializer=thread_initializer) as pool:
                future = pool.submit(
                    self.executor.invoke,
                    {"input": question},
                    {"callbacks": callbacks},
                )
                try:
                    result = future.result(timeout=DIAGNOSIS_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    future.cancel()
                    resilient = self._fallback_diagnose(question, trace_callback=trace_callback)
                    resilient["recovery_mode"] = "timeout_fallback"
                    resilient["agent_error"] = (
                        f"Diagnosis timed out after {DIAGNOSIS_TIMEOUT_SECONDS} seconds"
                    )
                    return resilient

            diagnosis_text = str(result.get("output", "")).strip()
            if not diagnosis_text or "Agent stopped due to iteration limit or time limit" in diagnosis_text:
                resilient = self._fallback_diagnose(question, trace_callback=trace_callback)
                resilient["recovery_mode"] = "resilient_live_data_diagnosis"
                resilient["agent_error"] = "ReAct agent did not produce a final diagnosis"
                return resilient
            
            return {
                "ok": True,
                "question": question,
                "diagnosis": diagnosis_text,
                "trace": trace_callback.trace_events if trace_callback else [],
            }
        except Exception as e:
            resilient = self._fallback_diagnose(question, trace_callback=trace_callback)
            resilient["recovery_mode"] = "resilient_live_data_diagnosis"
            resilient["agent_error"] = str(e)
            return resilient

    def _fallback_diagnose(
        self,
        question: str,
        trace_callback: Optional[DiagnosisTraceCallback] = None,
        degraded_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Provide a deterministic diagnosis when LangChain is unavailable."""
        trace_events: List[Dict[str, Any]] = []

        def record(event: Dict[str, Any]) -> None:
            trace_events.append(event)
            if trace_callback is not None:
                trace_callback.trace_events.append(event)

        record(
            {
                "event": "agent_action",
                "action": "fallback_diagnosis",
                "input": question,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        keyword = question.lower()
        symptom = "general failure"
        diagnosis = "The cluster appears healthy overall, but the question did not match a specific fault signature."
        remediation = "Review pod status, logs, and recent events for the affected service."
        impact = f"The affected workload may be unavailable or degraded in namespace {self.namespace}."
        validation = "Re-run status checks and confirm the workload reaches Ready state without new events."
        evidence_summary = ""

        def _is_cluster_unreachable(payload: Dict[str, Any]) -> bool:
            error_tokens = [
                "unable to connect to the server",
                "couldn't get current server api group list",
                "connectex",
                "connection refused",
                "no connection could be made",
                "i/o timeout",
                "context deadline exceeded",
            ]

            for step in payload.get("steps", []) if isinstance(payload, dict) else []:
                stderr = str(step.get("stderr", "") or "").lower()
                stdout = str(step.get("stdout", "") or "").lower()
                combined = f"{stderr}\n{stdout}"
                if any(token in combined for token in error_tokens):
                    return True

            top_error = str(payload.get("error", "") if isinstance(payload, dict) else "").lower()
            if any(token in top_error for token in error_tokens):
                return True

            return False

        def _extract_pods_stdout(payload: Dict[str, Any]) -> str:
            if not isinstance(payload, dict):
                return ""
            for step in payload.get("steps", []):
                command = str(step.get("command", "") or "").lower()
                if " get pods" in command and "-o json" not in command:
                    return str(step.get("stdout", "") or "")
            return ""

        try:
            status_snapshot = tool_get_cluster_status(namespace=self.namespace)
            record(
                {
                    "event": "tool_start",
                    "tool": "get_cluster_status",
                    "input": self.namespace,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            record(
                {
                    "event": "tool_end",
                    "output": json.dumps(status_snapshot, default=str)[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            status_snapshot = {"ok": False, "error": str(exc)}

        try:
            target_services = _extract_question_services(question, KNOWN_DEMO_SERVICES)
            evidence_snapshot = tool_collect_evidence_snapshot(
                namespace=self.namespace,
                services=target_services or None,
                log_tail_lines=120,
                include_describe=True,
            )
            record(
                {
                    "event": "tool_start",
                    "tool": "collect_evidence_snapshot",
                    "input": self.namespace,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            record(
                {
                    "event": "tool_end",
                    "output": json.dumps(evidence_snapshot, default=str)[:500],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception as exc:
            evidence_snapshot = {"ok": False, "error": str(exc)}

        cluster_unreachable = _is_cluster_unreachable(status_snapshot) or _is_cluster_unreachable(evidence_snapshot)
        pods_stdout = _extract_pods_stdout(status_snapshot)

        if cluster_unreachable:
            symptom = "Kubernetes API connectivity failure"
            diagnosis = (
                "The assistant could not read pods because kubectl cannot reach the Kubernetes API server "
                "for the active context."
            )
            remediation = (
                "Start or reconnect the local cluster, verify kubectl context/credentials, then re-run pod status checks."
            )
            impact = f"The assistant cannot inspect workloads in namespace {self.namespace} until cluster access is restored."
            validation = "Run `kubectl get pods` successfully against the active context, then retry diagnosis."
        elif any(token in keyword for token in ["read pods", "get pods", "pod status", "pods"]):
            if pods_stdout.strip():
                symptom = "Pod status request"
                diagnosis = "Pod list was read successfully from the target namespace."
                remediation = (
                    "Review the returned pod statuses and investigate any non-Running workloads with logs and events."
                )
            else:
                symptom = "Pod status request"
                diagnosis = "No pod data was returned for the requested namespace."
                remediation = "Confirm the namespace exists and contains workloads, then run pod status again."
        if not cluster_unreachable:
            live_analysis = _build_live_diagnosis(
                namespace=self.namespace,
                question=question,
                status_snapshot=status_snapshot,
                evidence_snapshot=evidence_snapshot,
            )
            diagnosis = live_analysis["diagnosis"]
            symptom = live_analysis["symptom"]
            remediation = live_analysis["remediation"]
            impact = live_analysis["impact"]
            validation = live_analysis["validation"]
            evidence_summary = live_analysis.get("evidence", "")

        result_text = (
            f"DIAGNOSIS: {diagnosis}\n"
            f"SYMPTOMS: {symptom}\n"
            f"IMPACT: {impact}\n"
            f"REMEDIATION: {remediation}\n"
            f"VALIDATION: {validation}\n"
            f"EVIDENCE: {evidence_summary or 'Live cluster data was used to build this diagnosis.'}"
        )

        record(
            {
                "event": "agent_finish",
                "output": result_text[:300],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        return {
            "ok": not cluster_unreachable,
            "question": question,
            "diagnosis": result_text,
            "status_snapshot": status_snapshot,
            "evidence_snapshot": evidence_snapshot,
            "trace": trace_events,
        }


def create_agent(
    namespace: str = DEFAULT_NAMESPACE,
    model: str = OLLAMA_MODEL,
    base_url: str = OLLAMA_BASE_URL,
) -> KubernetesAIDiagnosisAgent:
    """Factory function to create an AI diagnosis agent."""
    return KubernetesAIDiagnosisAgent(namespace=namespace, model=model, base_url=base_url)
