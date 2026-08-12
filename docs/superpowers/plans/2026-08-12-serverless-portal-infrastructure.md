# Serverless Portal Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 Firestore 기반 애플리케이션을 Firebase Hosting과 Cloud Run에 사전 배포하고, Cloud Run이 전용 IAM identity로 GKE DNS endpoint를 제어하도록 구성한다.

**Architecture:** 모든 서버리스 리소스는 `private-cloud-portal-demo-2` 프로젝트와 `asia-northeast3` 리전에 둔다. PowerShell 배포 스크립트는 반복 실행 가능하고 민감 정보를 파일에 쓰지 않으며, Firebase 기본 도메인과 Cloud Run 기본 URL에서 검증한 뒤 사용자 도메인 전환 계획으로 넘긴다.

**Tech Stack:** gcloud CLI, Firebase CLI 15.24.0+, Cloud Run, Cloud Firestore Native mode, Firebase Hosting, Artifact Registry, GKE DNS endpoint, IAM, Kubernetes RBAC, PowerShell

## Global Constraints

- GCP 프로젝트는 `private-cloud-portal-demo-2`이다.
- Cloud Run, Firestore, GKE는 `asia-northeast3` 서울 리전을 사용한다.
- GKE 클러스터는 `portal-demo-standard`, zone은 `asia-northeast3-a`이다.
- Cloud Run 서비스 이름은 `portal-backend`, 서비스 계정 이름은 `portal-cloud-run`이다.
- Cloud Run 최소 인스턴스는 0, 최대 인스턴스는 2이다.
- Cloud Run API는 공개 호출을 허용하지만 프로젝트 생성 제한은 서버에서 강제한다.
- 서비스 계정 키 파일과 `GOOGLE_APPLICATION_CREDENTIALS`를 만들거나 설정하지 않는다.
- GKE DNS endpoint 검증 전에는 기존 IP endpoint를 끄지 않는다.
- 기존 `portal.la-coruna.xyz` DNS와 GKE 포털은 이 계획에서 변경하거나 제거하지 않는다.
- 운영 변경 전후에 마이그레이션 로그와 블로그 초안을 갱신한다.

---

## File Structure

- `infra/gcp/serverless/01-enable-serverless-apis.ps1`: 필요한 API 활성화와 상태 확인
- `infra/gcp/serverless/02-create-firestore.ps1`: Firestore 위치 검증 또는 최초 생성
- `infra/gcp/serverless/03-configure-cloud-run-identity.ps1`: 서비스 계정과 최소 IAM
- `infra/gcp/serverless/cloud-run-gke-rbac.yaml`: IAM 서비스 계정용 Kubernetes RBAC
- `infra/gcp/serverless/04-enable-gke-dns-endpoint.ps1`: DNS endpoint 활성화와 확인
- `infra/gcp/serverless/05-deploy-cloud-run.ps1`: 이미지 빌드·push·Cloud Run 배포
- `infra/gcp/serverless/06-deploy-firebase-preview.ps1`: 프런트 빌드와 Hosting 배포
- `infra/gcp/serverless/07-smoke-test-serverless.ps1`: Cloud Run/Firebase 기능 검증
- `firebase.json`: Cloud Run rewrite와 SPA fallback
- `.firebaserc`: 저장소에 안전한 프로젝트 alias

---

### Task 1: 서버리스 API와 현재 리소스 인벤토리

**Files:**
- Create: `infra/gcp/serverless/01-enable-serverless-apis.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: enabled APIs and an inventory snapshot before mutation

- [ ] **Step 1: Write the idempotent API script**

```powershell
param([string]$ProjectId = 'private-cloud-portal-demo-2')
$ErrorActionPreference = 'Stop'
$apis = @(
  'run.googleapis.com',
  'firestore.googleapis.com',
  'firebase.googleapis.com',
  'firebasehosting.googleapis.com',
  'artifactregistry.googleapis.com',
  'container.googleapis.com',
  'iam.googleapis.com'
)
gcloud services enable @apis --project $ProjectId
gcloud services list --enabled --project $ProjectId --filter="name:($($apis -join ' OR '))" --format='value(name)'
```

- [ ] **Step 2: Record the pre-change inventory**

Run read-only commands for current Cloud Run services, Firestore databases, Firebase projects, GKE endpoint configuration, IAM service account existence, GKE workloads, ingress IPs, and current DNS answers. Store summaries, not access tokens, in the migration log.

- [ ] **Step 3: Run the API script and verify exact services**

Run: `powershell -File infra/gcp/serverless/01-enable-serverless-apis.ps1`

Expected: all seven API names appear; rerunning exits 0.

- [ ] **Step 4: Commit the API setup script and record**

```powershell
git add infra/gcp/serverless/01-enable-serverless-apis.ps1 docs/migration
git commit -m "infra: enable serverless portal APIs"
```

### Task 2: 서울 지역 Firestore 데이터베이스 준비

**Files:**
- Create: `infra/gcp/serverless/02-create-firestore.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: default Firestore Native database in `asia-northeast3`

- [ ] **Step 1: Write a location-safe creation script**

The script must first run:

```powershell
$existing = gcloud firestore databases describe --database='(default)' --project $ProjectId --format=json 2>$null
```

If a database exists, parse JSON and fail unless `locationId` equals `asia-northeast3` and type is Firestore Native. If it does not exist, run:

```powershell
gcloud firestore databases create --database='(default)' --location=asia-northeast3 --type=firestore-native --project=$ProjectId
```

- [ ] **Step 2: Dry-run the decision branch with mocked command output**

Extract validation into a PowerShell function and test three JSON fixtures: absent, Seoul Native, wrong location. Expected: create, no-op, hard failure respectively.

- [ ] **Step 3: Execute once and verify immutable location**

Run: `powershell -File infra/gcp/serverless/02-create-firestore.ps1`

Verify:

```powershell
gcloud firestore databases describe --database='(default)' --project private-cloud-portal-demo-2 --format='yaml(name,locationId,type)'
```

Expected: `locationId: asia-northeast3` and Native mode.

- [ ] **Step 4: Record and commit**

Record the chosen location, creation/no-op result, and the fact that location is immutable.

```powershell
git add infra/gcp/serverless/02-create-firestore.ps1 docs/migration
git commit -m "infra: provision Seoul Firestore database"
```

### Task 3: Cloud Run 전용 identity와 최소 IAM

**Files:**
- Create: `infra/gcp/serverless/03-configure-cloud-run-identity.ps1`
- Create: `infra/gcp/serverless/cloud-run-gke-rbac.yaml`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: `portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com`
- Produces: Firestore access and GKE connect permissions
- Produces: Kubernetes ClusterRoleBinding for the IAM user identity

- [ ] **Step 1: Write IAM script with explicit roles**

Create the account only if absent, then grant:

- `roles/datastore.user`
- `roles/container.viewer` for cluster metadata and DNS endpoint connect permission
- `roles/logging.logWriter`

Do not grant Editor, Owner, Service Account Admin, or Kubernetes Engine Admin.

- [ ] **Step 2: Write Kubernetes RBAC for IAM User subject**

```yaml
subjects:
  - kind: User
    apiGroup: rbac.authorization.k8s.io
    name: portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com
```

Rules must cover only get/list/watch/create/delete on namespaces, resourcequotas, services, pods, events, deployments, and ingresses. No secrets, RBAC, nodes mutation, exec, or logs permission.

- [ ] **Step 3: Validate RBAC before apply**

Run:

```powershell
kubectl apply --dry-run=client -f infra/gcp/serverless/cloud-run-gke-rbac.yaml
kubectl auth can-i create deployments --as=portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com --all-namespaces
kubectl auth can-i get secrets --as=portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com --all-namespaces
```

Before apply, first result for auth may be no. After apply, deployment must be yes and secrets must remain no.

- [ ] **Step 4: Apply identity and RBAC**

Run the IAM script, apply the RBAC manifest, and verify exact IAM policy entries and `kubectl auth can-i` results.

- [ ] **Step 5: Record and commit**

```powershell
git add infra/gcp/serverless/03-configure-cloud-run-identity.ps1 infra/gcp/serverless/cloud-run-gke-rbac.yaml docs/migration
git commit -m "infra: grant Cloud Run minimal portal access"
```

### Task 4: GKE DNS endpoint 활성화

**Files:**
- Create: `infra/gcp/serverless/04-enable-gke-dns-endpoint.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: reachable GKE DNS endpoint with IAM authentication
- Preserves: existing public and private IP endpoints

- [ ] **Step 1: Write precondition and update script**

Capture the complete control-plane endpoint configuration as JSON before update. Run:

```powershell
gcloud container clusters update portal-demo-standard `
  --zone asia-northeast3-a `
  --project private-cloud-portal-demo-2 `
  --enable-dns-access
```

Do not pass `--no-enable-ip-access`, authorized-network changes, or token/certificate-via-DNS flags.

- [ ] **Step 2: Execute and verify endpoint flags**

Expected after describe:

- DNS endpoint exists
- external DNS traffic is enabled
- Kubernetes token/certificate via DNS remains disabled
- public IP endpoint remains enabled for rollback

- [ ] **Step 3: Verify IAM connectivity from a temporary ADC context**

Use `gcloud container clusters get-credentials portal-demo-standard --zone asia-northeast3-a --dns-endpoint` and run read-only `kubectl get nodes`. Do not overwrite a required local context without recording and restoring the previous current context.

- [ ] **Step 4: Record before/after and commit**

```powershell
git add infra/gcp/serverless/04-enable-gke-dns-endpoint.ps1 docs/migration
git commit -m "infra: enable GKE DNS control plane access"
```

### Task 5: Cloud Run image and service deployment

**Files:**
- Create: `infra/gcp/serverless/05-deploy-cloud-run.ps1`
- Modify: `backend/Dockerfile`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Consumes: verified application image, Firestore, service identity, GKE DNS endpoint
- Produces: public Cloud Run service `portal-backend` in Seoul

- [ ] **Step 1: Add Cloud Run container contract test**

Ensure Dockerfile listens on `$PORT` using shell expansion or an entrypoint that defaults to 8080. Build locally and verify `/health` with the memory repository before cloud deployment.

- [ ] **Step 2: Write deployment script with immutable tag**

Use `git rev-parse --short HEAD` as the image tag under the existing Artifact Registry repository. Deploy with:

```powershell
gcloud run deploy portal-backend `
  --project private-cloud-portal-demo-2 `
  --region asia-northeast3 `
  --image $image `
  --service-account portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com `
  --allow-unauthenticated `
  --min 0 --max 2 `
  --cpu 1 --memory 512Mi `
  --concurrency 20 `
  --timeout 60 `
  --set-env-vars "APP_ENV=production,REPOSITORY_BACKEND=firestore,FIRESTORE_PROJECT_ID=private-cloud-portal-demo-2,FIRESTORE_DATABASE=(default),KUBE_AUTH_MODE=gke,GKE_CLUSTER_LOCATION=asia-northeast3-a,GKE_CLUSTER_NAME=portal-demo-standard,DEMO_MODE=true,DEMO_MAX_PROJECTS=3,DEMO_MAX_REPLICAS=1,DEMO_NAMESPACE_PREFIX=demo-,INGRESS_BASE_DOMAIN=apps.la-coruna.xyz,APP_INGRESS_CLASS_NAME=nginx"
```

Pass the discovered GKE DNS endpoint using a separate safe update if comma parsing makes a single environment argument ambiguous.

- [ ] **Step 3: Deploy and verify revision configuration**

Verify image digest, service account, min/max instances, timeout, concurrency, environment names, and public invoker policy. Do not print secret values because none should exist.

- [ ] **Step 4: Verify Cloud Run dependencies**

Call `/health` and `/api/platform-status`. Expected: Firestore `ok`; platform `AVAILABLE` or `RECOVERING`, but not authentication `UNAVAILABLE`. List projects must return an empty JSON array.

- [ ] **Step 5: Record revision evidence and commit**

```powershell
git add backend/Dockerfile infra/gcp/serverless/05-deploy-cloud-run.ps1 docs/migration
git commit -m "infra: deploy portal backend to Cloud Run"
```

### Task 6: Firebase Hosting과 Cloud Run rewrite

**Files:**
- Modify: `firebase.json`
- Create: `.firebaserc`
- Create: `infra/gcp/serverless/06-deploy-firebase-preview.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: Firebase default site for `private-cloud-portal-demo-2`
- Routes: `/api/**` and `/health` to Cloud Run; all other unmatched paths to `/index.html`

- [ ] **Step 1: Write exact rewrite order**

```json
{
  "hosting": {
    "public": "frontend/dist",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [
      {"source": "/api/**", "run": {"serviceId": "portal-backend", "region": "asia-northeast3", "pinTag": true}},
      {"source": "/health", "run": {"serviceId": "portal-backend", "region": "asia-northeast3", "pinTag": true}},
      {"source": "**", "destination": "/index.html"}
    ]
  }
}
```

- [ ] **Step 2: Validate Firebase config locally**

Run frontend tests/build, then `firebase emulators:exec --only hosting` with curl checks for `/`, `/projects`, and `/projects/demo-api-staging`. Expected: each SPA path returns index HTML.

- [ ] **Step 3: Deploy only Hosting to the default site**

Run:

```powershell
firebase use private-cloud-portal-demo-2
firebase deploy --only hosting --project private-cloud-portal-demo-2
```

Do not connect or change `portal.la-coruna.xyz` in this task.

- [ ] **Step 4: Verify Firebase default-domain routing**

Check `/`, `/projects`, direct detail route, `/health`, `/api/platform-status`, and `/api/projects`. Expected: SPA paths return HTML; API paths return JSON and no CORS error is needed because calls are same-origin.

- [ ] **Step 5: Record and commit**

```powershell
git add firebase.json .firebaserc infra/gcp/serverless/06-deploy-firebase-preview.ps1 docs/migration
git commit -m "infra: host portal frontend on Firebase"
```

### Task 7: 사전 배포 smoke test와 Spot 복구 UX 검증

**Files:**
- Create: `infra/gcp/serverless/07-smoke-test-serverless.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`

**Interfaces:**
- Produces: evidence that the default Firebase domain is safe for later cutover

- [ ] **Step 1: Write safe smoke-test script**

The script must:

1. Assert empty project list.
2. Create one allowed `demo-` project.
3. Assert status and audit log sequence.
4. Read Pods and Events.
5. Sync status.
6. Delete the project in `finally`.
7. Assert final `DELETED` and capacity can be claimed again.

Use a unique service name based on timestamp and never create more than one smoke project.

- [ ] **Step 2: Run functional smoke test against Firebase default domain**

Expected: all assertions pass and cleanup runs even if an intermediate assertion fails.

- [ ] **Step 3: Test platform states without destructive node replacement first**

Mock or temporarily inject platform status at the application test layer to verify `RECOVERING` and `UNAVAILABLE` UI. Confirm list/detail/audits remain visible and mutation rules match the design.

- [ ] **Step 4: Perform one controlled Spot recovery test with explicit checkpoint**

Before changing node state, confirm no active demo project, record current node and portal health, and retain the existing GKE portal. Select the only node carrying label `cloud.google.com/gke-spot=true`, record its Compute Engine instance name and zone, then run `gcloud compute instances delete $nodeName --zone $nodeZone --project private-cloud-portal-demo-2 --quiet`. GKE's managed instance group must recreate it. During recovery, poll every 15 seconds for:

- Firebase page HTTP 200
- `/health` HTTP 200
- platform state `RECOVERING` or `UNAVAILABLE`
- creation disabled in UI/API
- automatic return to `AVAILABLE`

Abort further mutation if the replacement node does not become Ready within the configured operational timeout; follow the existing GKE recovery runbook.

- [ ] **Step 5: Record exact timing and screenshots**

Record node disappearance, first degraded status, portal availability, replacement Ready time, automatic banner removal, and any deviations. Add sanitized screenshots to the blog candidate list.

- [ ] **Step 6: Commit smoke automation and evidence**

```powershell
git add infra/gcp/serverless/07-smoke-test-serverless.ps1 docs/migration
git commit -m "test: verify serverless portal on Firebase"
```

### Task 8: Infrastructure phase acceptance checkpoint

**Files:**
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: accepted Firebase default-domain deployment for the cutover plan

- [ ] **Step 1: Run final read-only configuration audit**

Verify Firestore location, Cloud Run digest and service identity, IAM roles, RBAC allow/deny checks, GKE DNS endpoint plus retained IP endpoint, Firebase rewrite, max instance count, and empty demo project capacity.

- [ ] **Step 2: Run the smoke test a second time from a clean state**

Expected: create, observe, sync, delete, and cleanup pass without manual repair.

- [ ] **Step 3: Check current billing SKUs and create a baseline**

Record current daily estimates for GKE cluster fee, Spot compute, load balancers, Cloud Run, Firestore, and Hosting. Do not claim savings until post-cutover billing data is available.

- [ ] **Step 4: Stop before custom-domain mutation**

Do not change DNS, attach `portal.la-coruna.xyz`, delete existing GKE portal workloads, remove MariaDB PVC, or alter the existing portal Load Balancer. Present the audit and smoke evidence for cutover approval.

- [ ] **Step 5: Commit final infrastructure record**

```powershell
git add docs/migration/firebase-cloud-run-firestore-migration-log.md
git commit -m "docs: record serverless infrastructure acceptance"
```
