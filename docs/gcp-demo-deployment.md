# GCP GKE Autopilot Public Demo Deployment

This guide prepares a public demo environment for the Private Cloud Self-Service Portal on GCP GKE Autopilot.

## Goal Architecture

```text
Recruiter Browser
  -> GKE HTTP Ingress
  -> portal-frontend Service
  -> React static dashboard
  -> /api requests
  -> portal-backend Service
  -> FastAPI backend
  -> MariaDB Service/PVC
  -> Kubernetes API through in-cluster ServiceAccount/RBAC
```

The backend runs inside the cluster. In GKE, it does not use a local kubeconfig file. The manifest sets `KUBE_CONTEXT` to an empty string so the app uses `config.load_incluster_config()`.

## Cost and Security Notes

This is a public demo, so keep the scope intentionally small.

- Use a temporary GCP project if possible.
- Set `DEMO_MODE=true`.
- Keep `DEMO_MAX_PROJECTS=3` and `DEMO_MAX_REPLICAS=1`.
- Allow only safe demo images: `nginx:latest`, `httpd:alpine`, `nginx-not-exist-demo:latest`.
- Do not commit service account keys, kubeconfig files, `.env` files, or real credentials.
- The backend RBAC grants only the resources needed by the demo workflow.
- No permissions are granted for Kubernetes `secrets`, `nodes`, or `clusterroles` resources.
- Run the cleanup script after the review window to avoid ongoing GKE and load balancer costs.

## Required GCP Services

- Kubernetes Engine API
- Artifact Registry API
- Compute Engine API

Enable them:

```powershell
.\infra\gcp\scripts\01-enable-apis.ps1 -ProjectId <PROJECT_ID>
```

## Create Artifact Registry

```powershell
.\infra\gcp\scripts\02-create-artifact-registry.ps1 `
  -ProjectId <PROJECT_ID> `
  -Region asia-northeast3 `
  -Repository portal-demo
```

## Build and Push Images

The frontend is built with `/api` as its API base URL so browser requests go through the same public Ingress.

```powershell
.\infra\gcp\scripts\03-build-and-push-images.ps1 `
  -ProjectId <PROJECT_ID> `
  -Region asia-northeast3 `
  -Repository portal-demo `
  -Tag latest `
  -ApiBaseUrl /api
```

This pushes:

```text
asia-northeast3-docker.pkg.dev/<PROJECT_ID>/portal-demo/portal-backend:latest
asia-northeast3-docker.pkg.dev/<PROJECT_ID>/portal-demo/portal-frontend:latest
```

## Create GKE Autopilot Cluster

```powershell
.\infra\gcp\scripts\04-create-gke-autopilot.ps1 `
  -ProjectId <PROJECT_ID> `
  -Region asia-northeast3 `
  -ClusterName portal-demo-autopilot
```

The script also runs `gcloud container clusters get-credentials` for kubectl access from the local machine.

## Deploy portal-system

Choose a throwaway DB password at deployment time. Do not commit it.

```powershell
.\infra\gcp\scripts\05-deploy-portal.ps1 `
  -ProjectId <PROJECT_ID> `
  -Region asia-northeast3 `
  -Repository portal-demo `
  -Tag latest `
  -DbPassword "<TEMP_DEMO_DB_PASSWORD>"
```

This creates:

- `portal-system` namespace
- `portal-db-secret` Secret from your local parameter
- MariaDB Deployment/PVC/Service
- backend Deployment/Service
- frontend Deployment/Service
- public GKE Ingress
- backend ServiceAccount, ClusterRole, and ClusterRoleBinding

## Public URL

GKE Ingress can take several minutes to assign an IP.

```powershell
kubectl -n portal-system get ingress portal-demo
```

Smoke test:

```powershell
.\infra\gcp\scripts\06-smoke-test.ps1
```

If you already know the URL:

```powershell
.\infra\gcp\scripts\06-smoke-test.ps1 -BaseUrl http://<INGRESS_IP>
```

Open the dashboard:

```text
http://<INGRESS_IP>/projects
```

## Demo Login / Access Token

The current MVP does not include user login. Public demo safety is enforced by demo-mode guardrails and minimal Kubernetes RBAC.

Recommended access pattern for a portfolio review:

- Share the public URL only with reviewers.
- Keep the review window short.
- Keep demo mode enabled.
- Clean up the cluster immediately after review.

If a stronger public gate is needed later, add Identity-Aware Proxy, a simple application login, or a short-lived reverse proxy in front of the Ingress.

## portfolio-demo Normal Scenario

Use the dashboard at `/projects/new`:

```text
service_name: portfolio-demo
environment: staging
image: nginx:latest
replicas: 1
cpu_request: 100m
cpu_limit: 500m
memory_request: 128Mi
memory_limit: 512Mi
expose_external: true
```

Expected result:

- project is created
- namespace is prefixed, for example `demo-portfolio-demo-staging`
- ResourceQuota, Deployment, Service, and Ingress are created
- Pod reaches Running
- Audit Log shows each provisioning step

## broken-demo Failure Scenario

Use the dashboard at `/projects/new`:

```text
service_name: broken-demo
environment: staging
image: nginx-not-exist-demo:latest
replicas: 1
cpu_request: 100m
cpu_limit: 500m
memory_request: 128Mi
memory_limit: 512Mi
expose_external: false
```

Expected result:

- Kubernetes accepts the Deployment
- Pod enters `ErrImagePull` or `ImagePullBackOff`
- Pod/Event views show the failure reason
- clicking status refresh calls `sync-status`
- project status changes to `FAILED`
- Audit Log includes `PROJECT_STATUS_SYNCED`

## Cleanup

Run cleanup as soon as the review/demo window is done.

```powershell
.\infra\gcp\scripts\99-cleanup-gcp-demo.ps1 `
  -ProjectId <PROJECT_ID> `
  -Region asia-northeast3 `
  -ClusterName portal-demo-autopilot
```

The script prompts for `DELETE` before deleting the cluster.

Optional Artifact Registry cleanup:

```powershell
gcloud artifacts repositories delete portal-demo `
  --project <PROJECT_ID> `
  --location asia-northeast3
```
