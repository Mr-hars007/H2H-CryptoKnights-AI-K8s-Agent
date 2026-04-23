from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List

import requests

NAMESPACE = os.getenv("AI_K8S_NAMESPACE", "ai-ops")
KUBECTL_BIN = os.getenv("AI_KUBECTL_BIN", "kubectl")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen:7b")


def run_kubectl(args: List[str]) -> str:
    try:
        completed = subprocess.run(
            [KUBECTL_BIN, *args],
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        return stdout if stdout else stderr
    except Exception as exc:
        return str(exc)


def get_pods_text() -> str:
    return run_kubectl(["get", "pods", "-n", NAMESPACE])


def get_pods_json() -> List[Dict[str, Any]]:
    raw = run_kubectl(["get", "pods", "-n", NAMESPACE, "-o", "json"])
    try:
        data = json.loads(raw)
    except Exception as e:
        return []

    pods: List[Dict[str, Any]] = []
    for item in data.get("items", []):
        metadata = item.get("metadata", {}) or {}
        status_obj = item.get("status", {}) or {}

        name = str(metadata.get("name", ""))
        status = str(status_obj.get("phase", "Unknown"))

        restarts = 0
        container_statuses = status_obj.get("containerStatuses", []) or []
        if container_statuses:
            first = container_statuses[0] or {}
            try:
                restarts = int(first.get("restartCount", 0) or 0)
            except Exception:
                restarts = 0

            state = first.get("state", {}) or {}
            waiting = state.get("waiting")
            terminated = state.get("terminated")

            # CRITICAL: Check waiting state first (CrashLoopBackOff appears here)
            if isinstance(waiting, dict) and waiting.get("reason"):
                status = str(waiting["reason"])
            elif isinstance(terminated, dict) and terminated.get("reason"):
                status = str(terminated["reason"])
        
        pods.append(
            {
                "name": name,
                "status": status,
                "restarts": restarts,
            }
        )

    return sorted(pods, key=lambda x: x["name"])


def get_pod_logs(pod_name: str, tail_lines: int = 40) -> str:
    return run_kubectl(
        [
            "logs",
            pod_name,
            "-n",
            NAMESPACE,
            "--tail",
            str(tail_lines),
            "--all-containers=true",
        ]
    )


def get_pod_describe(pod_name: str) -> str:
    return run_kubectl(["describe", "pod", pod_name, "-n", NAMESPACE])


class KubernetesAIDiagnosisAgent:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def _check_cluster_health(self, pods: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Foolproof health check.
        Returns: {
            "is_healthy": bool,
            "total_pods": int,
            "running_pods": int,
            "failed_pods": List[Dict]
        }
        """
        if not pods:
            return {
                "is_healthy": False,
                "total_pods": 0,
                "running_pods": 0,
                "failed_pods": [],
                "error": "No pods found in cluster"
            }

        total = len(pods)
        running = [p for p in pods if str(p["status"]).lower() == "running"]
        failed = [p for p in pods if str(p["status"]).lower() != "running"]

        return {
            "is_healthy": len(failed) == 0,
            "total_pods": total,
            "running_pods": len(running),
            "failed_pods": failed
        }

    def _call_ai_for_diagnosis(
        self, 
        user_question: str, 
        pods_text: str, 
        failed_pods: List[Dict[str, Any]],
        logs_collection: str
    ) -> str:
        """
        Call the AI model with full context including logs.
        Returns AI diagnosis or falls back to deterministic analysis.
        """
        # Build comprehensive context for AI
        failed_pods_context = "\n".join([
            f"Pod: {p['name']} | Status: {p['status']} | Restarts: {p['restarts']}"
            for p in failed_pods
        ])

        prompt = f"""You are a Kubernetes expert troubleshooting a production cluster.

USER QUESTION:
{user_question}

CURRENT POD STATUS:
{pods_text}

FAILED PODS SUMMARY:
{failed_pods_context}

DETAILED LOGS AND DIAGNOSTICS:
{logs_collection}

Your task:
1. Analyze the logs and pod states to identify the root cause
2. Explain what's wrong in simple terms
3. Provide step-by-step fix instructions
4. Mention any related issues you notice

Format your response as:

**Root Cause:**
[What's actually broken]

**Impact:**
[How this affects the system]

**Fix:**
[Step-by-step instructions to resolve]

**Additional Notes:**
[Any warnings or related issues]

Be specific and actionable. Reference actual pod names and log entries."""

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            ai_response = str(data.get("response", "") or "").strip()

            if ai_response:
                return ai_response
            else:
                return self._fallback_diagnosis(failed_pods)

        except Exception as e:
            # AI failed, use deterministic fallback
            return self._fallback_diagnosis(failed_pods) + f"\n\n(Note: AI model unavailable, using rule-based analysis. Error: {str(e)})"

    def _fallback_diagnosis(self, failed_pods: List[Dict[str, Any]]) -> str:
        """
        Rule-based diagnosis when AI is unavailable.
        """
        diagnoses = []
        
        for pod in failed_pods:
            name = pod["name"]
            status = pod["status"].lower()
            service = name.split("-")[0]
            
            if status in {"imagepullbackoff", "errimagepull"}:
                diagnoses.append(
                    f"**{service} ({name}):**\n"
                    f"- Root Cause: Cannot pull container image\n"
                    f"- Fix: Check image name in deployment, verify registry access and credentials\n"
                    f"- Command: `kubectl describe pod {name} -n {NAMESPACE}` to see exact error"
                )
            elif status == "crashloopbackoff":
                diagnoses.append(
                    f"**{service} ({name}):**\n"
                    f"- Root Cause: Application crashes immediately after starting\n"
                    f"- Fix: Check logs for startup errors, verify environment variables, check command/args\n"
                    f"- Command: `kubectl logs {name} -n {NAMESPACE}` for error details"
                )
            elif status in {"pending", "containercreating"}:
                diagnoses.append(
                    f"**{service} ({name}):**\n"
                    f"- Root Cause: Pod cannot be scheduled or started\n"
                    f"- Fix: Check node resources, verify volume mounts, check image availability\n"
                    f"- Command: `kubectl describe pod {name} -n {NAMESPACE}` for scheduling issues"
                )
            elif status == "oomkilled":
                diagnoses.append(
                    f"**{service} ({name}):**\n"
                    f"- Root Cause: Container ran out of memory\n"
                    f"- Fix: Increase memory limits in deployment or optimize application memory usage\n"
                    f"- Command: Check resource limits with `kubectl get pod {name} -n {NAMESPACE} -o yaml`"
                )
            else:
                diagnoses.append(
                    f"**{service} ({name}):**\n"
                    f"- Status: {status}\n"
                    f"- Fix: Run `kubectl describe pod {name} -n {NAMESPACE}` and check logs"
                )
        
        return "\n\n".join(diagnoses)

    def stream_run(self, user_question: str):
        """
        Streaming version of run(). 
        Yields dictionaries: 
        1. {"type": "context", "pods": ..., "logs": ..., "health": ...}
        2. {"type": "chunk", "content": ...}
        3. {"type": "final", "diagnosis": ...}
        """
        try:
            pods = get_pods_json()
            pods_text = get_pods_text()

            if not pods:
                yield {
                    "ok": False, 
                    "error": "Cannot access pods.",
                    "pods": pods_text,
                    "logs": ""
                }
                return

            health = self._check_cluster_health(pods)
            
            if health["is_healthy"]:
                diagnosis = (
                    f"✅ **Cluster Status: HEALTHY**\n\n"
                    f"All {health['total_pods']} pods are running normally.\n\n"
                    f"**System Status:** No issues detected."
                )
                yield {
                    "ok": True,
                    "type": "final",
                    "diagnosis": diagnosis,
                    "pods": pods_text,
                    "logs": "",
                    "is_healthy": True
                }
                return

            # Collect diagnostics for unhealthy cluster
            failed_pods = health["failed_pods"]
            logs_parts = []
            for pod in failed_pods:
                pname = pod["name"]
                logs_parts.append(f"--- {pname} Logs ---\n{get_pod_logs(pname)}\n--- {pname} Describe ---\n{get_pod_describe(pname)}")
            logs_collection = "\n".join(logs_parts)

            yield {
                "type": "context",
                "pods": pods_text,
                "logs": logs_collection,
                "health": health
            }

            # Prepare Prompt
            failed_pods_context = "\n".join([f"Pod: {p['name']} | Status: {p['status']}" for p in failed_pods])
            prompt = f"Troubleshoot this K8s cluster.\nQuestion: {user_question}\nStatus: {pods_text}\nFailed: {failed_pods_context}\nLogs: {logs_collection}\n\nFormat as Root Cause, Impact, Fix."

            response = requests.post(
                OLLAMA_URL,
                json={"model": self.model, "prompt": prompt, "stream": True},
                timeout=120,
                stream=True
            )
            response.raise_for_status()

            full_text = ""
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    content = chunk.get("response", "")
                    full_text += content
                    yield {"type": "chunk", "content": content}
                    if chunk.get("done"):
                        break

            yield {
                "ok": True,
                "type": "final",
                "diagnosis": full_text,
                "pods": pods_text,
                "logs": logs_collection,
                "is_healthy": False
            }

        except Exception as exc:
            yield {"ok": False, "error": str(exc)}

    def run(self, user_question: str) -> Dict[str, Any]:
        """
        Main entry point. Foolproof workflow:
        1. Get pods
        2. Check health
        3. If healthy: return healthy status
        4. If unhealthy: collect logs and ask AI
        """
        try:
            # Step 1: Get pod data
            pods = get_pods_json()
            pods_text = get_pods_text()

            if not pods:
                return {
                    "ok": False,
                    "error": f"Cannot access pods in namespace '{NAMESPACE}'. Cluster may not be initialized.",
                    "pods": pods_text,
                    "logs": "",
                }

            # Step 2: Health check
            health = self._check_cluster_health(pods)

            # Step 3: If healthy, return immediately
            if health["is_healthy"]:
                return {
                    "ok": True,
                    "diagnosis": (
                        f"✅ **Cluster Status: HEALTHY**\n\n"
                        f"All {health['total_pods']} pods are running normally.\n\n"
                        f"**Running Services:**\n" + 
                        "\n".join([f"- {p['name']}" for p in pods]) +
                        f"\n\n**System Status:** No issues detected. All services are operational."
                    ),
                    "pods": pods_text,
                    "logs": "",
                    "is_healthy": True,
                }

            # Step 4: Cluster is unhealthy - collect detailed diagnostics
            failed_pods = health["failed_pods"]
            logs_collection_parts = []

            for pod in failed_pods:
                pod_name = pod["name"]
                
                # Collect logs
                logs = get_pod_logs(pod_name, tail_lines=50)
                describe = get_pod_describe(pod_name)
                
                logs_collection_parts.append(f"\n{'='*60}")
                logs_collection_parts.append(f"POD: {pod_name}")
                logs_collection_parts.append(f"STATUS: {pod['status']}")
                logs_collection_parts.append(f"RESTARTS: {pod['restarts']}")
                logs_collection_parts.append(f"{'='*60}")
                logs_collection_parts.append(f"\n--- LOGS ---\n{logs}")
                logs_collection_parts.append(f"\n--- DESCRIBE OUTPUT ---\n{describe}")

            logs_collection = "\n".join(logs_collection_parts)

            # Step 5: Ask AI to diagnose with full context
            ai_diagnosis = self._call_ai_for_diagnosis(
                user_question,
                pods_text,
                failed_pods,
                logs_collection
            )

            return {
                "ok": True,
                "diagnosis": (
                    f"⚠️ **Cluster Status: DEGRADED**\n\n"
                    f"**Health Check:**\n"
                    f"- Total Pods: {health['total_pods']}\n"
                    f"- Running: {health['running_pods']}\n"
                    f"- Failed: {len(failed_pods)}\n\n"
                    f"**AI Diagnosis:**\n\n{ai_diagnosis}"
                ),
                "pods": pods_text,
                "logs": logs_collection,
                "is_healthy": False,
            }

        except Exception as exc:
            # Absolute fallback for any unexpected errors
            return {
                "ok": False,
                "error": f"Diagnosis failed: {str(exc)}",
                "pods": "",
                "logs": "",
            }


def create_agent(model: str = DEFAULT_MODEL) -> KubernetesAIDiagnosisAgent:
    return KubernetesAIDiagnosisAgent(model=model)