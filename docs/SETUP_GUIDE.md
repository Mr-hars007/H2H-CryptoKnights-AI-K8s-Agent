# H2H CryptoKnights Setup Guide

This guide walks through the easiest way to set up the project and open the web GUI.

## Best Supported Path

Use:

- Windows PowerShell
- Docker Desktop
- `kind`
- `kubectl`
- Python 3.10+
- Ollama

The web app is built with Streamlit and the launcher script is PowerShell-first, so this path avoids most environment issues.

## What You Will End Up With

By the end of this guide, you will have:

- a local Kubernetes demo cluster
- the sample microservices deployed in namespace `ai-ops`
- Ollama serving a local model
- the Streamlit web GUI open at `http://localhost:8501`

## 1. Install Prerequisites

Install these tools before continuing:

- Docker Desktop
- `kind`
- `kubectl`
- Python 3.10 or newer
- Ollama

After installation, open PowerShell and verify everything:

```powershell
docker --version
kind --version
kubectl version --client
python --version
ollama --version
```

If any command fails, fix that first before continuing.

## 2. Open the Project Folder

In PowerShell:

```powershell
cd C:\path\to\H2H-CryptoKnights-AI-K8s-Agent
```

## 3. Create the Python Environment

Run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell says script execution is disabled, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the virtual environment again:

```powershell
.\.venv\Scripts\Activate.ps1
```

## 4. Start Ollama

Open a new PowerShell window and run:

```powershell
ollama serve
```

Leave that window open.

Open another PowerShell window and download the model used by this project:

```powershell
ollama pull qwen:7b
```

You only need to pull the model once.

## 5. Optional: Set Ollama Environment Variables

Back in the PowerShell window where you will launch the app, set:

```powershell
$env:OLLAMA_MODEL="qwen:7b"
$env:OLLAMA_BASE_URL="http://localhost:11434"
```

If you are running Ollama inside WSL instead of Windows, start it in WSL like this:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

Then keep the Windows-side base URL as:

```powershell
$env:OLLAMA_BASE_URL="http://localhost:11434"
```

## 6. Start the Web GUI

From the project root in PowerShell, run:

```powershell
.\start-diagnosis.ps1 web
```

What this command does:

- checks that `kubectl`, Python, and Ollama are available
- activates `.venv` if needed
- starts the Streamlit server
- opens your browser to `http://localhost:8501`

If the browser does not open automatically, manually visit:

```text
http://localhost:8501
```

## 7. Initialize the App in the Browser

When the page loads, use the left sidebar.

Set or confirm:

- `Namespace`: `ai-ops`
- `Ollama Model`: `qwen:7b`
- `Ollama Base URL`: `http://localhost:11434`

Then click:

```text
Initialize
```

This step is important. The app will:

- create a local `kind` cluster if one does not already exist
- switch `kubectl` to that cluster
- apply the Kubernetes manifests in [`k8s/manifests/`](../k8s/manifests/)
- wait for the `gateway`, `orders`, and `payments` deployments
- start background traffic
- initialize the AI diagnosis agent

Wait until the UI shows that initialization completed successfully.

## 8. Use the Web GUI

After initialization, you can work in two modes.

### Diagnosis Mode

Use this mode to ask what is wrong in the cluster.

Good starter questions:

- `What's the overall cluster health and are there any issues?`
- `Why are the orders pods failing?`
- `Are any pods stuck in Pending state?`

Useful controls:

- `Analyze` runs an AI-assisted diagnosis
- `Snapshot` shows current cluster evidence
- `Discover Services` finds live services
- `Generate Traffic` creates in-cluster traffic to surface problems

### Chaos Mode

Use this mode to inject a safe demo failure, then switch back to Diagnosis Mode to investigate it.

Available fault scenarios include:

- `crashloop_orders`
- `pending_payments`
- `misconfigured_service_payments`
- `oomkill_gateway`

Typical workflow:

1. Open `Chaos`
2. Choose a scenario
3. Click `Inject`
4. Switch to `Diagnosis`
5. Ask why the service is failing
6. Return to `Chaos`
7. Click `Revert All`

## 9. Fastest Demo Flow

If you just want to prove the whole thing works:

1. Start `ollama serve`
2. Run `ollama pull qwen:7b`
3. Run `.\start-diagnosis.ps1 web`
4. Open `http://localhost:8501`
5. Click `Initialize`
6. In `Chaos`, inject `crashloop_orders`
7. In `Diagnosis`, ask `Why are the orders pods failing?`

## Troubleshooting

### The page does not open

Manually open:

```text
http://localhost:8501
```

If Streamlit did not start, rerun:

```powershell
.\start-diagnosis.ps1 web
```

### `python` is not recognized

Make sure Python is installed and on your Windows PATH. Then reopen PowerShell and run:

```powershell
python --version
```

### Ollama is not responding

Make sure `ollama serve` is running, then test:

```powershell
curl http://localhost:11434/api/tags
```

If you are using WSL-hosted Ollama, make sure you started it with:

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

### `Initialize` fails in the web UI

Check these first:

- Docker Desktop is running
- `kind --version` works
- `kubectl version --client` works
- Ollama is reachable at the URL shown in the sidebar

### The cluster starts but pods never become ready

Inspect the cluster in PowerShell:

```powershell
kubectl get pods -n ai-ops
kubectl get events -n ai-ops
```

## Other Ways to Run It

### Interactive CLI

```powershell
.\start-diagnosis.ps1 cli
```

### Single Diagnosis Query

```powershell
.\start-diagnosis.ps1 diagnose --question "Why are orders failing?"
```

## Relevant Files

- [README.md](../README.md)
- [start-diagnosis.ps1](../start-diagnosis.ps1)
- [ui/streamlit_app.py](../ui/streamlit_app.py)
- [backend/app.py](../backend/app.py)
