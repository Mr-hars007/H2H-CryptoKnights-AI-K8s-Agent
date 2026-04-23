# 🛠️ Setup Guide — AI Kubernetes Diagnosis System

This guide will help you set up the full system including:

* Kubernetes (via Docker Desktop / kind)
* Ollama (LLM backend)
* Streamlit UI
* AI Agent backend

---

## ✅ 1. Prerequisites

Make sure you have:

* Python 3.10+
* Docker Desktop (Kubernetes enabled)
* WSL (recommended for Ollama)
* kubectl installed

Check:

```bash
kubectl version --client
```

---

## ✅ 2. Start Kubernetes

If using Docker Desktop:

* Enable Kubernetes in settings

Verify:

```bash
kubectl get nodes
```

---

## ✅ 3. Install Ollama (WSL)

Inside WSL:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama:

```bash
ollama serve
```

Pull model:

```bash
ollama pull qwen:7b
```

Test:

```bash
ollama run qwen:7b
```

---

## ✅ 4. Setup Python Environment

In project root:

```bash
pip install -r requirements.txt
```

Minimal requirements:

```
streamlit
requests
pandas
```

---

## ✅ 5. Verify kubectl Access

```bash
kubectl get pods -A
```

If this fails → fix kubeconfig before continuing.

---

## ✅ 6. Run Application

```bash
streamlit run ui/streamlit_app.py
```

---

## 🚀 7. First Use

1. Open browser (auto)
2. Click **🚀 Initialize Cluster**
3. Wait ~10 seconds
4. Check pods:

```bash
kubectl get pods -n ai-ops
```

---

## 💥 8. Chaos Testing

Use sidebar:

* CrashLoop Orders
* Pending Payments
* Break Gateway

---

## 🧹 9. Cleanup

From UI:

* Click **Delete Cluster**

OR manually:

```bash
kubectl delete namespace ai-ops
```

---

## ⚠️ Common Issues

### ❌ Model not found

```bash
ollama pull qwen:7b
```

### ❌ kubectl not working

Check context:

```bash
kubectl config current-context
```

### ❌ Pods stuck in ImagePullBackOff

Fix:

```bash
kubectl set image deployment/orders nginx=nginx -n ai-ops
```

---

## ✅ System Architecture

* Streamlit UI → user interaction
* Python Agent → builds prompt
* Ollama → LLM reasoning
* kubectl → real cluster data

---

You’re now running a real AI-powered Kubernetes debugging system.
