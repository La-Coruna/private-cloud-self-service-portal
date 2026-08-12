# Serverless Portal Cutover and Rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 Firebase 기본 도메인 배포를 `portal.la-coruna.xyz`로 안전하게 전환하고 24시간 관찰 후 별도 승인에 따라 기존 GKE 포털을 정리한다.

**Architecture:** 사용자 도메인 전환 전 기존 GKE 엔드포인트, DNS, 매니페스트와 이미지를 롤백 자산으로 보존한다. Firebase Hosting에 custom domain을 준비한 뒤 낮은 TTL로 DNS를 전환하고, 신규와 기존 구조를 24시간 병행한다. 제거는 데이터 없는 데모 프로젝트, stateless 포털, MariaDB 저장소 순서로 분리하며 저장소 삭제에는 별도 승인이 필요하다.

**Tech Stack:** Firebase Hosting custom domains, DNS, GKE, kubectl, Cloud Run, Firestore, PowerShell, curl, Cloud Logging, GCP Billing

## Global Constraints

- 사용자 주소는 `portal.la-coruna.xyz`를 유지한다.
- 신규 주소 검증 전 기존 GKE 포털을 변경하거나 삭제하지 않는다.
- DNS 전환 전 기존 GKE Load Balancer IP와 DNS 레코드를 기록한다.
- 최소 24시간 신규 구조와 기존 GKE 포털을 병행한다.
- MariaDB PVC와 기존 포털 제거는 관찰 완료 후 별도 사용자 승인이 있어야 한다.
- 사용자 프로젝트용 Spot 노드와 공유 ingress-nginx는 유지한다.
- DNS 전환 실패 시 기존 GKE Load Balancer로 즉시 되돌릴 수 있어야 한다.
- 모든 외부 변경과 검증 결과를 마이그레이션 로그와 공개용 블로그 초안에 기록한다.

---

## File Structure

- `infra/gcp/serverless/08-inventory-cutover.ps1`: 롤백 자산과 현재 DNS/클러스터 상태 캡처
- `infra/gcp/serverless/09-clean-demo-projects.ps1`: 관리 label 기반 기존 데모 Namespace 정리
- `infra/gcp/serverless/10-verify-custom-domain.ps1`: DNS/HTTPS/rewrite 검증
- `infra/gcp/serverless/11-monitor-cutover.ps1`: 24시간 관찰용 읽기 전용 검사
- `infra/gcp/serverless/12-remove-legacy-portal.ps1`: 승인 후 기존 stateless 포털 제거
- `infra/gcp/serverless/13-remove-legacy-database.ps1`: 별도 승인 후 MariaDB/PVC 제거
- `docs/migration/firebase-cloud-run-firestore-migration-log.md`: 운영 타임라인과 롤백 근거
- `docs/migration/firebase-cloud-run-firestore-blog-draft.md`: 최종 공개용 초안

---

### Task 1: 전환 전 롤백 자산 인벤토리

**Files:**
- Create: `infra/gcp/serverless/08-inventory-cutover.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: exact legacy endpoint, DNS, image, manifest, and workload inventory

- [ ] **Step 1: Write a read-only inventory script**

The script must capture and print sanitized summaries of:

- `Resolve-DnsName portal.la-coruna.xyz`
- `kubectl get ingress portal-demo -n portal-system -o yaml`
- portal frontend/backend/MariaDB Deployment image and replicas
- portal Services, PVC, PV, ServiceAccount, ClusterRole, ClusterRoleBinding
- current GKE node and user Namespace list
- Artifact Registry backend/frontend image digests
- current Firebase default URL and Cloud Run URL
- current Git commit

Write no kubeconfig, token, Secret, or database password to disk.

- [ ] **Step 2: Execute and identify the exact rollback target**

Expected: one current `portal.la-coruna.xyz` address that maps to the legacy GKE portal Load Balancer, plus working direct health and project endpoints.

- [ ] **Step 3: Verify legacy redeploy manifests without applying**

Run:

```powershell
kubectl apply --dry-run=client -k infra/gcp
docker manifest inspect $recordedBackendImage
docker manifest inspect $recordedFrontendImage
```

Expected: manifests validate and recorded image digests remain available.

- [ ] **Step 4: Record rollback instructions and commit**

The log must state the exact DNS value to restore, health endpoint, rollout commands, and the fact that MariaDB PVC remains untouched.

```powershell
git add infra/gcp/serverless/08-inventory-cutover.ps1 docs/migration
git commit -m "ops: capture portal cutover rollback assets"
```

### Task 2: 기존 데모 사용자 리소스 정리

**Files:**
- Create: `infra/gcp/serverless/09-clean-demo-projects.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Deletes only Namespaces labeled `app.kubernetes.io/managed-by=self-service-portal` and prefixed `demo-`
- Preserves `portal-system`, `ingress-nginx`, system Namespaces, and node pool

- [ ] **Step 1: Write preview-by-default cleanup script**

The script must list candidate Namespace names and their managed-by label. Without `-Apply`, exit after preview. With `-Apply`, reject any name that does not start with `demo-` or lacks the exact label.

- [ ] **Step 2: Preview and cross-check Firestore empty state**

Expected: Firestore project list is empty and every cleanup candidate is an old demo Namespace. If a candidate is not documented, stop for inspection.

- [ ] **Step 3: Apply cleanup and wait for deletion**

Delete only validated candidates. Poll each Namespace until absent with a bounded timeout. Do not remove shared ingress-nginx LoadBalancer or its namespace.

- [ ] **Step 4: Verify cluster baseline and record**

Expected: no managed demo Namespace remains; GKE node, portal-system, ingress-nginx, and shared ingress IP remain healthy.

- [ ] **Step 5: Commit the safe cleanup script and record**

```powershell
git add infra/gcp/serverless/09-clean-demo-projects.ps1 docs/migration
git commit -m "ops: clean legacy demo namespaces safely"
```

### Task 3: Firebase custom domain 준비와 DNS TTL 축소

**Files:**
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`

**Interfaces:**
- Produces: Firebase Hosting custom-domain verification records
- Preserves: legacy traffic until Firebase requests final serving records

- [ ] **Step 1: Inspect the authoritative DNS zone and current TTL**

Determine the authoritative nameservers and the system managing `la-coruna.xyz`. Record only provider name, current A/CNAME values, and TTL; do not record account identifiers or session data.

- [ ] **Step 2: Add `portal.la-coruna.xyz` to Firebase Hosting**

Use the authenticated Firebase console or supported Hosting API to add the existing custom domain. If Firebase requests a TXT ownership record, add only that TXT first while keeping the legacy A/CNAME record.

- [ ] **Step 3: Verify ownership without switching traffic**

Wait until Firebase reports ownership verified and supplies the exact serving A/AAAA or CNAME records. Do not replace the legacy serving record yet.

- [ ] **Step 4: Lower the legacy DNS TTL**

Set the portal record TTL to 300 seconds where the provider permits it. Wait at least the previous TTL duration before traffic cutover so caches can expire.

- [ ] **Step 5: Record generated records and rollback value**

Record the exact Firebase-provided serving values, verification status, certificate status, previous TTL, new TTL, and legacy rollback value. Do not publish ownership TXT values in the blog draft.

- [ ] **Step 6: Commit documentation checkpoint**

```powershell
git add docs/migration
git commit -m "docs: record Firebase custom domain readiness"
```

### Task 4: 사용자 도메인 DNS 전환

**Files:**
- Create: `infra/gcp/serverless/10-verify-custom-domain.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Produces: `portal.la-coruna.xyz` served by Firebase Hosting
- Consumes: exact serving records generated by Firebase

- [ ] **Step 1: Write pre-cutover and post-cutover assertions**

The verification script accepts `-ExpectedDnsValue` and checks:

- authoritative and recursive DNS answers
- HTTPS certificate hostname
- `/`, `/projects`, and a direct SPA route return HTML
- `/health`, `/api/platform-status`, `/api/projects` return JSON
- response headers identify Firebase Hosting where applicable

- [ ] **Step 2: Run pre-cutover checks against both deployments**

Expected: legacy custom domain healthy, Firebase default domain healthy, Firestore empty, Cloud Run platform status not authentication-failed.

- [ ] **Step 3: Replace only the portal serving record**

Apply the exact Firebase-provided A/AAAA or CNAME records. Do not change wildcard `*.apps.la-coruna.xyz`, the shared ingress-nginx record, or any unrelated DNS record.

- [ ] **Step 4: Monitor propagation and certificate state**

Poll authoritative DNS, public recursive DNS, Firebase custom-domain status, HTTP, and HTTPS. Accept temporary mixed answers within the previous TTL window. If the Firebase certificate is not ready, keep monitoring the documented provisioning state rather than disabling HTTPS checks permanently.

- [ ] **Step 5: Execute rollback if acceptance fails**

Rollback trigger: Firebase reports a terminal domain error, HTTPS remains unusable for 60 minutes after DNS propagation is confirmed, or API rewrite fails for 15 consecutive minutes while legacy health is available. Restore the recorded legacy DNS value with TTL 300, verify legacy `/health`, and record the rollback. If Firebase documents certificate provisioning as actively progressing, preserve the Firebase default domain for continued diagnosis after traffic is rolled back.

- [ ] **Step 6: On success, run one full create/read/sync/delete test**

Use the production custom domain and a unique allowed demo project. Cleanup in `finally`. Expected: SPA, API, Firestore, Cloud Run, GKE, shared application ingress, and deletion all pass.

- [ ] **Step 7: Record evidence and commit**

```powershell
git add infra/gcp/serverless/10-verify-custom-domain.ps1 docs/migration
git commit -m "ops: cut portal domain over to Firebase"
```

### Task 5: 24시간 병행 관찰

**Files:**
- Create: `infra/gcp/serverless/11-monitor-cutover.ps1`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`

**Interfaces:**
- Produces: read-only observations at cutover, +1h, +6h, and +24h
- Preserves: legacy GKE portal workloads and MariaDB PVC

- [ ] **Step 1: Write a read-only monitoring script**

For each run, output timestamp and status for custom-domain DNS, TLS, Firebase root, API health, platform status, project list, Cloud Run latest revision/error count, Firestore access, legacy GKE portal pods, MariaDB pod/PVC, GKE nodes, and shared ingress-nginx.

- [ ] **Step 2: Capture immediate and +1 hour checkpoints**

Expected: custom domain and API remain healthy, no unexpected Cloud Run error burst, legacy portal remains available as rollback.

- [ ] **Step 3: Capture +6 hour checkpoint**

Repeat functional read checks and run one create/delete smoke test only if capacity is empty. Record Cloud Run cold-start behavior and Firestore/GKE latency without inventing an SLA.

- [ ] **Step 4: Capture +24 hour checkpoint**

Expected: no unresolved severity error, no capacity leak, custom domain certificate healthy, platform state recovers after any Spot event, and rollback assets still exist.

- [ ] **Step 5: Summarize acceptance or rollback recommendation**

If acceptance fails, restore legacy DNS before any cleanup. If acceptance passes, present exact resources proposed for removal and request separate user approval.

- [ ] **Step 6: Commit observation evidence**

```powershell
git add infra/gcp/serverless/11-monitor-cutover.ps1 docs/migration
git commit -m "docs: record 24-hour portal cutover observation"
```

### Task 6: 승인 후 기존 stateless 포털 제거

**Files:**
- Create: `infra/gcp/serverless/12-remove-legacy-portal.ps1`
- Modify: `infra/gcp/kustomization.yaml`
- Modify: `docs/gcp-demo-deployment.md`
- Modify: `README.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Deletes: legacy portal Ingress, frontend/backend Deployments and Services, old in-cluster portal ServiceAccount/RBAC
- Preserves: MariaDB Deployment, Service, PVC, PV until Task 7 approval
- Preserves: user Spot node pool and ingress-nginx

- [ ] **Step 1: Stop and request explicit removal approval**

Present the 24-hour results and exact Kubernetes resources. Do not continue on an implied approval from the original migration request.

- [ ] **Step 2: Write preview-by-default removal script**

Without `-Apply`, list each exact resource and its current UID. With `-Apply`, re-read and require the UID to match the preview record before deletion. Scale MariaDB to zero only if rollback no longer needs the live database process; keep its PVC.

- [ ] **Step 3: Remove legacy stateless resources**

Delete `portal-demo` Ingress first so its dedicated GCE Load Balancer can be released, then frontend/backend Deployments and Services, old Kubernetes ServiceAccount, ClusterRoleBinding, and ClusterRole. Do not delete the namespace.

- [ ] **Step 4: Verify unaffected resources**

Expected: Firebase custom domain and Cloud Run remain healthy; GKE Spot node, ingress-nginx LoadBalancer, user project provisioning, MariaDB PVC, and Firestore remain present as intended.

- [ ] **Step 5: Update manifests and deployment documentation**

Remove legacy portal components from the active serverless deployment path. Keep a clearly labeled rollback section referencing the commit before removal rather than silently deleting historical knowledge.

- [ ] **Step 6: Record load balancer release and commit**

```powershell
git add infra/gcp/serverless/12-remove-legacy-portal.ps1 infra/gcp/kustomization.yaml docs/gcp-demo-deployment.md README.md docs/migration
git commit -m "infra: remove legacy GKE portal workloads"
```

### Task 7: 별도 승인 후 MariaDB 저장소 제거

**Files:**
- Create: `infra/gcp/serverless/13-remove-legacy-database.ps1`
- Modify: `infra/gcp/kustomization.yaml`
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`

**Interfaces:**
- Deletes: legacy MariaDB Deployment, Service, PVC, PV where reclaim policy permits, and remaining empty `portal-system` namespace

- [ ] **Step 1: Stop and request irreversible storage approval**

State that demo data is intentionally not migrated and PVC deletion removes the easiest data-level rollback. Show PVC, PV, storage class, reclaim policy, and estimated residual disk cost.

- [ ] **Step 2: Write an exact-target storage removal script**

Require both `-Apply` and `-ConfirmDataLoss DELETE_LEGACY_PORTAL_DB`. Resolve PVC to PV and verify both belong to `portal-system` before deletion. Never use a glob, recursive filesystem command, or namespace-wide delete until exact resources are checked.

- [ ] **Step 3: Delete MariaDB resources after approval**

Delete Deployment and Service, then PVC. Verify PV behavior from its reclaim policy. Delete `portal-system` namespace only if `kubectl get all,pvc,secret,serviceaccount -n portal-system` contains no unrelated resource.

- [ ] **Step 4: Verify final GKE scope and billing resources**

Expected: only user workload infrastructure and shared ingress-nginx remain on GKE; no portal GCE Ingress Load Balancer, portal disk, portal Pods, or MariaDB resources remain.

- [ ] **Step 5: Update active kustomization and commit**

```powershell
git add infra/gcp/serverless/13-remove-legacy-database.ps1 infra/gcp/kustomization.yaml docs/migration
git commit -m "infra: remove legacy portal database"
```

### Task 8: 최종 비용 검증과 블로그 초안 완성

**Files:**
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`
- Modify: `README.md`
- Modify: `docs/03-architecture.md`

**Interfaces:**
- Produces: final operational handoff and publishable migration narrative

- [ ] **Step 1: Capture final architecture and health evidence**

Record Firebase custom domain, Cloud Run revision/digest, Firestore location, GKE platform status, one successful project lifecycle, and remaining Kubernetes resources.

- [ ] **Step 2: Compare billing after sufficient data is available**

Compare the same-length period before and after removal. Separate fixed GKE cluster fee, Spot compute, portal GCE Load Balancer, shared ingress Load Balancer, Cloud Run, Firestore, and Hosting. Label estimates as estimates and measured billing as measured.

- [ ] **Step 3: Complete the blog narrative**

Include incident timeline, DB retry mitigation, architecture decision, six project states versus three platform states, Firestore repository refactor, Cloud Run IAM/RBAC, GKE DNS endpoint, Firebase rewrite, rollback plan, Spot recovery result, 24-hour observation, resource cleanup, cost outcome, and lessons learned.

- [ ] **Step 4: Sanitize the public draft**

Search for email addresses, project numbers, tokens, authorization headers, Secret values, database passwords, private IPs, and local user paths. Keep public domain, public project ID if already documented, generic commands, and non-sensitive architecture identifiers only where useful.

- [ ] **Step 5: Update architecture documentation**

Replace the active portal diagram with Firebase Hosting → Cloud Run → Firestore/GKE DNS API → Spot workloads. Preserve a labeled legacy architecture section for incident context.

- [ ] **Step 6: Run final repository verification and commit**

Run backend tests, frontend tests/lint/build, manifest dry-runs for remaining Kubernetes resources, and script syntax checks. Then:

```powershell
git add docs/migration README.md docs/03-architecture.md
git commit -m "docs: complete serverless portal migration story"
```
