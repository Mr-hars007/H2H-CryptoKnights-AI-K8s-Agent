# Phase 2 Cluster Baseline

This directory contains the Phase 2 baseline for the H2H CryptoKnights AI K8s Agent.

## What gets deployed

- Namespace: `ai-ops`
- 3 microservices (each as Deployment + Service):
  - `gateway`
  - `orders`
  - `payments`

All services expose port `80` and route to container port `5678`.

## Deploy

```powershell
kubectl apply -k k8s/manifests
```

## Verify

```powershell
kubectl -n ai-ops get pods
kubectl -n ai-ops get svc
kubectl -n ai-ops wait --for=condition=available deployment/gateway deployment/orders deployment/payments --timeout=120s
```

## Smoke test (optional)

Use temporary port-forwarding for each service:

```powershell
kubectl -n ai-ops port-forward svc/gateway 8080:80
kubectl -n ai-ops port-forward svc/orders 8081:80
kubectl -n ai-ops port-forward svc/payments 8082:80
```

Then test in separate terminals:

```powershell
Invoke-WebRequest http://localhost:8080
Invoke-WebRequest http://localhost:8081
Invoke-WebRequest http://localhost:8082
```

Each endpoint should return a service-specific healthy message.
