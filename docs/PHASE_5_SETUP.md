# Phase 5: AI Diagnosis Loop - Setup & Testing Guide

## Overview

Phase 5 implements a complete AI-powered Kubernetes diagnosis loop with:
- LLM-driven diagnosis agent using LangChain + Ollama
- Multi-turn conversation support with memory
- Integrated tool-calling for evidence collection
- Two interfaces: Interactive CLI and Streamlit Web UI

## Prerequisites

### 1. Working Kubernetes Cluster
```powershell
# Verify cluster is running with demo apps
kubectl get pods -n ai-ops
kubectl get svc -n ai-ops
```

### 2. Ollama Running Locally
```powershell
# Terminal 1: Start Ollama server
ollama serve

# Terminal 2: Pull a model
ollama pull llama2
```

Or use a different model:
```powershell
ollama pull mistral
ollama pull neural-chat
```

### 3. Python Dependencies
```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install Phase 5 dependencies
pip install -r requirements.txt
```

## Quick Start

### Option A: Interactive CLI (Recommended for First Test)

```powershell
# Activate venv if not already done
.\.venv\Scripts\Activate.ps1

# Launch interactive diagnosis assistant
python backend/app.py cli
```

**In the CLI:**
```
[DIAGNOSIS] > Why are the orders pods failing?
[DIAGNOSIS] > /status
[DIAGNOSIS] > /scenarios
[DIAGNOSIS] > /mode chaos
[CHAOS] > /scenarios
[CHAOS] > What happens if I inject a CrashLoopBackOff?
```

### Option B: Single Diagnosis Query

```powershell
python backend/app.py diagnose --question "Why are the orders pods in CrashLoopBackOff?"
```

### Option C: Streamlit Web UI

```powershell
cd ui/
streamlit run streamlit_app.py

# Opens http://localhost:8501
```

Then:
1. Click "Initialize Agent" button
2. Switch to "Diagnosis" mode
3. Ask questions about cluster issues
4. Or switch to "Chaos Testing" to inject faults

## Demo Flow (5-10 Minutes)

### Scenario 1: Diagnose Existing Failure

```powershell
# Terminal 1: Start CLI
python backend/app.py cli

# Terminal 2: Inject a fault
kubectl patch deployment orders -n ai-ops --type strategic --patch-file k8s/chaos/manifests/crashloop-orders-patch.yaml

# Back in Terminal 1, ask:
[DIAGNOSIS] > Why are the orders pods in CrashLoopBackOff?
[DIAGNOSIS] > What's the root cause?
[DIAGNOSIS] > How can I fix it?
[DIAGNOSIS] > /mode chaos
[CHAOS] > /scenarios
[CHAOS] > Revert all faults
```

### Scenario 2: Chaos Testing + Diagnosis

```powershell
# In CLI:
[DIAGNOSIS] > /mode chaos
[CHAOS] > /scenarios

# Agent will list available scenarios
# Then:
[CHAOS] > Inject a pending_payments scenario
[CHAOS] > /mode diagnosis

# Switch back to diagnosis mode
[DIAGNOSIS] > Why are the payments pods pending?

# Get diagnosis from AI agent
```

## Commands Reference

### CLI Special Commands

| Command | Purpose |
|---------|---------|
| `/status` | Get quick cluster status |
| `/scenarios` | List chaos scenarios |
| `/mode diagnosis\|chaos` | Switch modes |
| `/save` | Save conversation to file |
| `/load <file>` | Load previous conversation |
| `/clear` | Clear history |
| `/history` | Show conversation history |
| `/exit` | Exit and save |

### app.py Commands

```powershell
# List all scenarios
python backend/app.py list

# Inject a specific fault
python backend/app.py inject --scenario crashloop_orders

# Get cluster status
python backend/app.py status

# Collect comprehensive evidence
python backend/app.py snapshot

# Monitor cluster health
python backend/app.py monitor --samples 5 --interval 10

# Run diagnosis query
python backend/app.py diagnose --question "Why is service X failing?"

# Interactive CLI
python backend/app.py cli

# Streamlit UI
streamlit run ui/streamlit_app.py
```

## Understanding the AI Agent

### How It Works

1. **You ask a question** about cluster issues
2. **Agent collects evidence** using available tools:
   - Pod status and logs
   - Kubernetes events
   - Service configurations
   - Resource constraints
3. **LLM reasons** about symptoms and patterns
4. **Agent provides diagnosis** with:
   - Root cause analysis
   - Observable symptoms
   - Impact assessment
   - Step-by-step remediation
   - Validation steps

### Tool Calls

Agent has access to these tools:
- `collect_evidence` - Full cluster snapshot
- `get_cluster_status` - Quick status check
- `list_fault_scenarios` - Available chaos tests
- `inject_fault` - Create controlled failures
- `revert_fault` - Restore baseline
- `monitor_health` - Health trending

### Reasoning Trace

Every diagnosis includes a reasoning trace showing:
- Which tools the agent called
- What data it collected
- How it reasoned to the conclusion

Check traces in: `backend/traces/`

## Configuration

### Environment Variables

```powershell
# Kubernetes settings
$env:AI_K8S_NAMESPACE = "ai-ops"
$env:AI_K8S_SERVICES = "gateway,orders,payments"

# Ollama settings
$env:OLLAMA_BASE_URL = "http://localhost:11434"
$env:OLLAMA_MODEL = "llama2"

# Monitoring defaults
$env:AI_MONITOR_SAMPLES = "5"
$env:AI_MONITOR_INTERVAL_SECONDS = "10"
```

## Troubleshooting

### "Connection refused" to Ollama

```powershell
# Check if Ollama is running
ollama serve

# Check if model is installed
ollama pull llama2

# Verify URL
curl http://localhost:11434/api/tags
```

### "Module not found" errors

```powershell
# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Verify installation
python -c "from langchain_ollama import ChatOllama; print('OK')"
```

### Slow diagnosis

- First diagnosis is slower (LLM initialization)
- Subsequent queries are faster
- Use `--samples 3` for monitoring if too slow
- Try `mistral` or `neural-chat` models for speed

## Test Matrix

| Mode | Scenario | Expected Result |
|------|----------|-----------------|
| Diagnosis | Ask about CrashLoopBackOff | Identifies restart loops, suggests pod logs check |
| Diagnosis | Ask about Pending pods | Identifies resource constraints, suggests node capacity check |
| Diagnosis | Ask about OOMKilled | Identifies memory limit, suggests resource increase |
| Chaos | Inject CrashLoopBackOff | Fault successfully injected |
| Chaos | Revert all faults | Cluster restored to baseline |
| CLI | Multi-turn conversation | Context preserved across queries |
| CLI | Save conversation | JSON file created in `backend/traces/conversations/` |
| Streamlit | Initialize agent | Agent loads without errors |
| Streamlit | Diagnosis query | Result displayed with reasoning trace |

## Example Diagnosis Output

```
DIAGNOSIS: CrashLoopBackOff in orders deployment (High confidence)
Probable cause: Container init command failure or missing dependency

SYMPTOMS:
- orders-xxx pods restarting every 10-15 seconds
- ImagePullBackOff or Exited errors in kubectl describe
- Events show "Back-off restarting failed container"

IMPACT:
- Orders service unavailable to clients
- Cascading failure: gateway cannot reach orders, returns 503

REMEDIATION:
1. Examine pod logs: kubectl logs <pod> -n ai-ops
2. Check init container logs: kubectl logs <pod> -c <init-container>
3. Verify image registry: kubectl describe pod <pod>
4. Check environment variables and ConfigMaps
5. Review recent deployment changes

VALIDATION:
- Pod transitions to Running state
- No restart events in recent history
- Service responds to health checks
```

## Next Steps

After Phase 5:
- Phase 6: UX polish and feature refinement
- Phase 7: Stabilization and release readiness
- Production deployment with FastAPI backend
- Multi-cluster support
- Integration with monitoring systems

## Support

For issues or questions:
- Check trace files in `backend/traces/`
- Review agent reasoning in CLI/Streamlit UI
- Run `python backend/app.py status` for cluster health
- Check Ollama status: `ollama serve` in separate terminal
