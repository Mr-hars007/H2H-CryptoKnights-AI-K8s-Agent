# Phase 3 Controlled Fault Injection

This directory contains the Phase 3 chaos scenarios for local, controlled fault injection.

## Scenarios

- `crashloop_orders`: Forces `orders` pods into CrashLoopBackOff.
- `pending_payments`: Makes `payments` unschedulable with oversized requests.
- `misconfigured_service_payments`: Breaks `payments` Service routing by changing `targetPort`.
- `oomkill_gateway`: Triggers `gateway` OOMKilled restarts with memory stress.

## Patch files

Patch manifests are in `k8s/chaos/manifests/` and are applied with `kubectl patch --type strategic --patch-file ...`.

## Safety constraints

- Intended for local clusters only.
- Revert by reapplying Phase 2 baseline manifests.
- Run one scenario at a time for cleaner diagnosis output.

## Quick verification commands

```powershell
kubectl -n ai-ops get pods
kubectl -n ai-ops get events --sort-by=.lastTimestamp | Select-Object -Last 20
kubectl -n ai-ops describe pod <pod-name>
```
