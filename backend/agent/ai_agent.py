import requests
import subprocess

OLLAMA_URL = "http://localhost:11434/api/generate"


def run_kubectl(cmd: list):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip() if result.stdout else result.stderr.strip()
    except Exception as e:
        return str(e)


def get_pods():
    return run_kubectl(["kubectl", "get", "pods", "-A"])


def get_logs():
    pods = run_kubectl(["kubectl", "get", "pods", "-n", "ai-ops", "-o", "name"]).splitlines()

    logs = ""
    for pod in pods:
        pod_name = pod.split("/")[-1]

        logs += f"\n--- Logs for {pod_name} ---\n"
        logs += run_kubectl([
            "kubectl", "logs", pod_name,
            "-n", "ai-ops",
            "--tail=20"
        ]) + "\n"

    return logs


class KubernetesAIDiagnosisAgent:
    def __init__(self, model="qwen:7b"):
        self.model = model

    def run(self, user_question: str):
        try:
            pods = get_pods()
            logs = get_logs()

            prompt = f"""
You are a Kubernetes debugging expert.

User question:
{user_question}

Pods:
{pods}

Logs:
{logs}

IMPORTANT:
- If any pod has ImagePullBackOff, ErrImagePull, CrashLoopBackOff → treat as FAILURE
- Prioritize failed pods over running ones
- Explain EXACT failure reason
- Give FIX commands

Answer clearly:
"""

            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                },
                timeout=120
            )

            data = response.json()

            if "response" not in data:
                return {"ok": False, "error": str(data)}

            return {
                "ok": True,
                "diagnosis": data["response"].strip(),
                "pods": pods,
                "logs": logs,
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}


def create_agent(model="qwen:7b"):
    return KubernetesAIDiagnosisAgent(model)