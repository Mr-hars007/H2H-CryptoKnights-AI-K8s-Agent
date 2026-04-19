# H2H CryptoKnights: AI K8s Agent

AI Kubernetes Assistant for Diagnosis and Controlled Chaos Testing

## Tagline

Ask why your cluster is failing, or safely make it fail, and let the AI explain everything.

## Problem Statement

Debugging Kubernetes failures is often slow and manual. Engineers must inspect pod states, logs, events, restarts, and configurations across multiple services before they can identify root causes.

Current pain points:

- Time-consuming investigations
- Error-prone manual correlation
- High dependency on deep Kubernetes expertise
- Limited proactive resilience testing

At the same time, many teams do not intentionally test failure scenarios in local environments, so reliability gaps are discovered only during incidents.

## Proposed Solution

Build a dual-mode AI assistant for local Kubernetes clusters:

### Fix Mode (Diagnosis)

- Collects cluster evidence (pods, logs, events, describe output)
- Monitors cluster health and symptom changes over time
- Finds probable root cause for failures
- Produces clear natural language explanations
- Recommends actionable next steps

### Chaos Mode (Resilience Testing)

- Injects safe, controlled failures in local sandbox clusters
- Simulates realistic failure classes:
  - Resource limit violations
  - CrashLoopBackOff scenarios
  - Misconfigured services
  - Pending pods
- Validates observability and recovery behavior

## Why This Project

Most tools either monitor systems or run chaos tests separately. This project combines both:

- Break safely (Chaos Mode)
- Diagnose intelligently (Fix Mode)
- Explain transparently (reasoning + tool-call logs)

This creates a complete and practical reliability workflow.

## Core Features (MVP - All Complete ✅)

- ✅ Dual mode operation: Fix and Chaos
- ✅ Local Kubernetes support (Minikube/kind)
- ✅ Demo app with 3 microservices
- ✅ Controlled failure injection for 4 fault classes
- ✅ Agentic loop (LangChain ReAct with Ollama)
- ✅ Natural language to kubectl command translation and execution
- ✅ AI-assisted root cause analysis with actionable recommendations
- ✅ Conversation context memory for multi-turn queries
- ✅ Transparent tool-call and reasoning trace logs
- ✅ CLI and web UI (Streamlit) interfaces

## Scope Locks (Anti-Scope-Creep)

- Only 1 local cluster
- Only 4 fault scenarios in MVP
- Only 1 primary demo flow with 2 variants
- Only 1 AI model path
- Only 1 interface (CLI or Streamlit)

## Tech Stack

### Platform

- Kubernetes (Minikube or kind)
- Docker

### Backend

- Python 3.10+
- LangChain + LangChain-Ollama (AI orchestration)
- Kubernetes Python client + kubectl wrappers

### AI Layer

- Ollama (local LLM runtime)
- ReAct Agent Pattern (Reasoning + Acting)

### Frontend

- Streamlit (web UI)
- PowerShell CLI (interactive terminal)

## High-Level Architecture

```text
User (CLI/UI)
  |
  v
AI Agent Orchestrator
  |-- Tool: get_pod_status
  |-- Tool: get_logs
  |-- Tool: get_events
  |-- Tool: describe_resource
  |-- Tool: inject_fault (Chaos Mode)
  |
  v
Kubernetes API / kubectl
  |
  v
Local Cluster (3 microservices)

LLM (Ollama) provides reasoning + response generation
```

## Requirements Alignment

- Local Kubernetes cluster with at least 3 microservices: planned via Minikube/kind + demo app
- Fault injection coverage: resource limit violations, CrashLoopBackOff, misconfigured services, pending pods
- Agentic loop: natural language query -> tool selection -> kubectl execution -> reasoning -> root-cause summary
- Context retention: follow-up questions across services and namespaces
- Full transparency: every tool call and reasoning step logged

## Model Choice Rationale

The project uses Ollama-hosted open-source LLMs to keep execution local, reproducible, and controllable in a DevOps workflow.

- Local inference improves privacy and reduces dependency on external APIs
- Lower latency for iterative diagnostic loops
- Easier to instrument and audit reasoning traces with tool-call logs
- Practical fit for local Kubernetes demos and constrained environments

The default plan is one model path to reduce complexity during MVP delivery.

## Planned Repository Structure

```text
.
|-- README.md
|-- backend/
|   |-- app.py
|   |-- agent/
|   |-- tools/
|   \-- traces/
|-- k8s/
|   |-- manifests/
|   \-- chaos/
|-- ui/
|   \-- streamlit_app.py
\-- docs/
   \-- demo-script.md
```

## Setup Instructions

### Prerequisites

- Docker Desktop
- Minikube or kind
- kubectl
- Python 3.10+
- Ollama

### 1. Verify Local Tooling

```powershell
docker --version
kubectl version --client
minikube version
python --version
ollama --version
```

### 2. Start Local Kubernetes Cluster

```powershell
minikube start --cpus=4 --memory=8192
kubectl get nodes
```

### 3. Create Project Namespace

```powershell
kubectl create namespace ai-ops --dry-run=client -o yaml | kubectl apply -f -
kubectl config set-context --current --namespace=ai-ops
```

### 4. Deploy Demo Microservices (3 Services Minimum)

```powershell
kubectl apply -f k8s/manifests/
kubectl get pods -w
```

### 5. Install Python Dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 6. Start Local Model Runtime

In a separate terminal:

```powershell
ollama serve
```

In another terminal, pull a model:

```powershell
ollama pull llama2
```

### 7. Launch AI Diagnosis Assistant

**Interactive CLI (Recommended):**

```powershell
python backend/app.py cli
```

**Web UI (Streamlit):**

```powershell
streamlit run ui/streamlit_app.py
```

**Or use the launcher:**

```powershell
.\start-diagnosis.ps1 cli        # Interactive CLI
.\start-diagnosis.ps1 web        # Streamlit web UI
```

**Single Diagnosis Query:**

```powershell
python backend/app.py diagnose --question "Why are the orders pods failing?"
```

### 8. Validate End-to-End Flow

1. Launch CLI: `python backend/app.py cli`
2. Ask: "Why is service X failing?"
3. Agent collects evidence and provides diagnosis
4. Review reasoning trace showing all tool calls
5. Follow remediation recommendations
6. Verify cluster recovery

## Phase 3 Chaos Operations

List available scenarios:

```powershell
python backend/app.py list
```

Inject a scenario:

```powershell
python backend/app.py inject --scenario crashloop_orders --namespace ai-ops
```

Check cluster snapshot:

```powershell
python backend/app.py status --namespace ai-ops
```

Revert all chaos changes to the baseline manifests:

```powershell
python backend/app.py revert --namespace ai-ops
```

Available scenario keys:

- `crashloop_orders`
- `pending_payments`
- `misconfigured_service_payments`
- `oomkill_gateway`

## Phase 4 Observability Operations

Collect a full evidence snapshot (pods, services, deployments, events, per-service pod logs, and describe outputs):

```powershell
python backend/app.py snapshot --namespace ai-ops
```

Collect a lighter snapshot without `describe` calls:

```powershell
python backend/app.py snapshot --namespace ai-ops --no-describe
```

Monitor cluster health over time:

```powershell
python backend/app.py monitor --namespace ai-ops --samples 5 --interval 10
```

List recent trace files:

```powershell
python backend/app.py traces --limit 20
```

View a specific trace by ID:

```powershell
python backend/app.py trace --trace-id <trace-id>
```

Trace files are persisted under `backend/traces/` as JSON and include command metadata plus full evidence payloads.

## Phase 5: AI Diagnosis Loop

### Interactive CLI

```powershell
python backend/app.py cli
```

In the CLI, ask diagnosis questions:

```
> Why are the orders pods failing?
> /status        (get cluster status)
> /scenarios     (list chaos scenarios)
> /mode chaos    (switch to chaos mode)
> Inject a CrashLoopBackOff
> /mode diagnosis (switch back)
> How do I fix this?
```

### Web UI

```powershell
streamlit run ui/streamlit_app.py
```

Then:
1. Click "Initialize Agent" in the sidebar
2. Ask questions in Diagnosis mode, or
3. Test with Chaos mode (inject faults, then diagnose)

### Single Query

```powershell
python backend/app.py diagnose --question "Why are the payments pods pending?"
```

## Demo Flow (Target)

1. Deploy sample app in local cluster
2. Inject a failure from Chaos Mode
3. Ask agent: Why is service X failing?
4. Agent collects logs/events/status via tools
5. Agent returns root cause + recommended fix
6. Apply fix and show recovery

## Diagnostic Conversation Coverage (✅ Implemented)

Supported diagnostic conversations:

1. CrashLoopBackOff root-cause and fix guidance
2. Pending pod diagnosis due to scheduling/resource constraints
3. Resource limit violation analysis (OOMKilled or throttling symptoms)
4. Misconfigured service diagnosis (selector/port mismatch)
5. Follow-up context queries with multi-turn memory

## Development Roadmap

### Phase 1: Foundation

- Repository initialized
- Architecture and MVP frozen
- README baseline created

### Phase 2: Cluster Baseline

- Local cluster + 3-service app deployed

### Phase 3: Controlled Fault Injection

- Chaos injection scenarios implemented

### Phase 4: Observability and Evidence Collection

- Evidence collection and trace logging added

### Phase 5: AI Diagnosis Loop

- AI diagnosis loop integrated end-to-end

### Phase 6: Product Experience

- Dual-mode UX polished (CLI/UI)

### Phase 7: Stabilization and Release Readiness

- Stabilization, documentation, demo prep

## Current Status

✅ **Phase 5 Complete!**

All core functionality implemented and tested:

- Phase 2: Demo app in `k8s/manifests/` (3 microservices)
- Phase 3: Chaos injection in `k8s/chaos/` and `backend/tools/chaos_injector.py` (4 scenarios)
- Phase 4: Evidence collection in `backend/tools/evidence_collector.py` and trace logging
- Phase 5: AI agent in `backend/agent/ai_agent.py` with CLI (`backend/cli.py`) and web UI (`ui/streamlit_app.py`)

The system is production-ready for local Kubernetes diagnosis and chaos testing workflows.

## Expected Impact

- Reduce MTTR for Kubernetes incidents
- Improve confidence through proactive local chaos tests
- Make Kubernetes troubleshooting more accessible
- Encourage transparent and explainable AI-assisted operations

## Team

- Harsha C - Project Lead, AI and Backend
  - GitHub: https://github.com/Mr-hars007
- Manoj Kumar C - Kubernetes and Platform Engineering
  - GitHub: https://github.com/Manoj-KumarC

## Deployed Link

- Deployment URL: TBD
- Hosting target: Vercel (UI) + Render/Railway (API), or equivalent managed platform

## Demo and Screenshots

Visual evidence and demonstration assets will be published after core development milestones are completed.

- Planned Screenshot 1: Cluster overview with 3 running microservices
- Planned Screenshot 2: Fault injection event and observable failure state
- Planned Screenshot 3: AI diagnosis output with tool-call trace
- Planned Demo Video (3 to 5 minutes): publication scheduled after feature-complete validation

## Project Outputs

1. Demonstrable end-to-end assistant flow with at least 5 distinct diagnostic conversations
2. Source repository with architecture, setup instructions, and model selection rationale
3. Engineering retrospective covering what worked, what did not, and a scaling path to production clusters with 200+ services

## Disclaimer

All fault injections are performed only in a controlled local environment.
No production or external systems are targeted.
