# Troubleshooting Guide

This guide documents common local development and demo issues for the Private Cloud Self-Service Portal.

## kubeconfig context errors

### Symptoms

- `/health` reports Kubernetes connectivity failure.
- Project creation fails at Namespace creation.
- `kubectl get nodes` points to a different cluster than the intended kind cluster.

### Check

```powershell
kubectl config current-context
kubectl config get-contexts
kubectl get nodes
```

### Fix

Switch to the intended kind context:

```powershell
kubectl config use-context kind-private-cloud
```

If the cluster name is different, use the context shown by `kubectl config get-contexts`.

## kind hostPort not applied

### Symptoms

- Ingress resources exist, but `*.localtest.me:8080` does not open in the browser.
- `curl http://browser-demo-staging.localtest.me:8080` fails to connect.

### Cause

kind port mappings are defined when the cluster is created. If the cluster was created without hostPort mappings, installing ingress-nginx later is not enough for local browser access.

### Fix

Recreate the cluster with the provided script:

```powershell
.\infra\scripts\create-kind-cluster.ps1
.\infra\scripts\install-ingress-nginx.ps1
```

Temporary validation option:

```powershell
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80
```

## ingress-nginx missing or not ready

### Symptoms

- Ingress exists, but traffic is not routed.
- `kubectl get pods -n ingress-nginx` shows no controller Pod or a non-ready controller.

### Check

```powershell
kubectl get ns ingress-nginx
kubectl get pods -n ingress-nginx
kubectl get ingress -A
```

### Fix

```powershell
.\infra\scripts\install-ingress-nginx.ps1
kubectl wait --namespace ingress-nginx `
  --for=condition=Ready pod `
  --selector=app.kubernetes.io/component=controller `
  --timeout=120s
```

## ImagePullBackOff

### Symptoms

- Project creation succeeds, but the Pod does not become Running.
- Pod container state is `waiting` with reason `ImagePullBackOff` or `ErrImagePull`.

### Check

```powershell
kubectl get pods -n bad-image-staging
kubectl describe pod -n bad-image-staging <pod-name>
```

Portal APIs:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/projects/<id>/pods
Invoke-RestMethod http://127.0.0.1:8000/api/projects/<id>/events
```

### Fix

- Verify the image name and tag exist.
- Add imagePullSecret support if using a private registry.
- Call `POST /api/projects/<id>/sync-status` to reflect the failure in DB status.

## ResourceQuota exceeded

### Symptoms

- Deployment is created, but Pod creation fails.
- Events mention quota limits or forbidden resource requests.

### Check

```powershell
kubectl describe resourcequota -n <namespace>
kubectl get events -n <namespace> --sort-by=.lastTimestamp
```

Portal API:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/projects/<id>/events
```

### Fix

- Lower CPU/memory request and limit values.
- Reduce replica count.
- Adjust ResourceQuota policy if the platform owner approves it.

## CORS errors

### Symptoms

- API calls work in FastAPI docs but fail from `http://127.0.0.1:5173`.
- Browser DevTools shows preflight or CORS errors.

### Check

- `frontend/.env` has the expected API base URL.
- FastAPI CORS middleware allows the Vite dev origin.
- Browser Network tab shows successful `OPTIONS` responses.

Expected frontend value:

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Expected local origins:

```text
http://127.0.0.1:5173
http://localhost:5173
```

## DB column drift after model changes

### Symptoms

- API fails with an unknown column error.
- Example: `Unknown column 'ingress_host'`.
- The code model has a field that the existing local MariaDB volume does not have.

### Cause

The MVP uses SQLAlchemy metadata and startup compatibility checks instead of full Alembic migrations. Older local DB volumes can drift from the current model.

### Fix

- Check backend startup logs for compatibility updates.
- For a disposable local environment, reset the Docker volume and recreate the DB.
- For production-grade evolution, add Alembic migrations.

## Project status mismatch and sync-status

### Symptoms

- The project status in DB is `RUNNING` because Kubernetes accepted the Deployment.
- The actual Pod is not Running due to `ImagePullBackOff`, `CrashLoopBackOff`, quota errors, or scheduling issues.

### Cause

Kubernetes resource creation success is not the same as Pod readiness. A Deployment can be accepted while its Pod later fails.

### Fix

Call the status sync endpoint:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/projects/<id>/sync-status
```

What it does:

1. Lists project Pods using project labels.
2. Inspects container state and waiting reason.
3. Reads Kubernetes Events for context.
4. Updates `Project.status` to `RUNNING`, `FAILED`, or `PROVISIONING`.
5. Stores `PROJECT_STATUS_SYNCED` or `PROJECT_STATUS_SYNC_FAILED` in Audit Log.

The React detail page uses the same API through the `Status refresh` button.
