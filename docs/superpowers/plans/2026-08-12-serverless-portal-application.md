# Serverless Portal Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MariaDB에 결합된 포털 애플리케이션을 Firestore 저장소와 GKE 장애 인지 UI를 사용하는 Cloud Run/Firebase Hosting 준비 상태로 전환한다.

**Architecture:** 프로젝트 도메인 모델, 저장소 Protocol, 프로젝트 서비스, FastAPI Router를 분리한다. 운영에서는 Firestore Repository를, 테스트에서는 InMemory Repository를 주입하며, GKE 연결 상태와 프로젝트 생명주기는 별도의 상태 축으로 유지한다. React SPA는 문자열 Namespace ID와 플랫폼 상태 API를 사용하고 읽기 요청만 제한적으로 재시도한다.

**Tech Stack:** Python 3.12, FastAPI 0.115.6, Pydantic 2, google-cloud-firestore, google-auth, Kubernetes Python client, React 19, TypeScript 6, TanStack Query 5, Axios, Vitest, unittest

## Global Constraints

- 프로젝트 상태는 `REQUESTED`, `PROVISIONING`, `RUNNING`, `FAILED`, `DELETING`, `DELETED` 6종을 유지한다.
- 플랫폼 상태는 `AVAILABLE`, `RECOVERING`, `UNAVAILABLE` 3종을 별도로 사용한다.
- 프로젝트 ID와 감사 로그의 `project_id`는 Kubernetes Namespace 문자열이다.
- 공개 데모 제한은 활성 프로젝트 3개, replica 1개, 기존 이미지와 서비스 이름 prefix 허용 목록이다.
- 변경 요청인 생성, 삭제, 상태 동기화는 브라우저에서 자동 재시도하지 않는다.
- GKE 장애 중에도 Firestore 기반 목록, 상세, 감사 로그는 제공한다.
- 운영 자격 증명 파일을 코드, 환경 변수 또는 저장소에 추가하지 않는다.
- 기존 데모 데이터는 이전하지 않고 Firestore를 빈 상태로 시작한다.
- 각 작업 완료 시 마이그레이션 로그와 블로그 초안에 공개 가능한 근거를 기록한다.

---

## File Structure

### Backend

- `backend/app/domain.py`: 프로젝트, 감사 로그, 상태 enum의 순수 도메인 모델
- `backend/app/repositories/base.py`: 저장소 Protocol과 용량 관련 예외
- `backend/app/repositories/memory.py`: 단위 테스트용 in-memory 저장소
- `backend/app/repositories/firestore.py`: Firestore 문서 매핑과 트랜잭션
- `backend/app/dependencies.py`: 설정에 따른 Repository와 Service 주입
- `backend/app/services/project_service.py`: 프로젝트 생명주기와 GKE orchestration
- `backend/app/services/platform_status.py`: GKE API와 Ready 노드 기반 플랫폼 상태 판정
- `backend/app/k8s_auth.py`: local kubeconfig 또는 GKE IAM 인증 설정
- `backend/app/k8s_client.py`: Kubernetes 리소스 조작과 조회만 담당
- `backend/app/routers/projects.py`: HTTP 입출력과 예외 매핑
- `backend/app/routers/platform.py`: 플랫폼 상태 API
- `backend/app/main.py`: 앱 구성과 health endpoint

### Frontend

- `frontend/src/lib/types.ts`: 문자열 ID와 플랫폼 상태 타입
- `frontend/src/lib/api.ts`: 같은-origin API와 읽기 전용 재시도
- `frontend/src/hooks/usePlatformStatus.ts`: 15초 플랫폼 상태 polling
- `frontend/src/components/PlatformStatusBanner.tsx`: 복구/불가 안내
- `frontend/src/App.tsx`: 전역 플랫폼 상태 배너
- `frontend/src/pages/*.tsx`: 문자열 ID, 작업 차단, GKE unavailable 처리

### Documentation

- `docs/migration/firebase-cloud-run-firestore-migration-log.md`: 시간순 원본 기록
- `docs/migration/firebase-cloud-run-firestore-blog-draft.md`: 공개용 서술 초안

---

### Task 1: 순수 도메인 모델과 문자열 프로젝트 ID

**Files:**
- Create: `backend/app/domain.py`
- Modify: `backend/app/schemas.py`
- Modify: `frontend/src/lib/types.ts`
- Test: `backend/tests/test_domain.py`
- Test: `frontend/src/api.test.ts`

**Interfaces:**
- Produces: `ProjectStatus`, `PlatformAvailability`, `Project`, `AuditLog`, `utc_now()`
- Produces: `ProjectResponse.id: str`, `AuditLogResponse.project_id: str`

- [ ] **Step 1: Write failing backend domain tests**

```python
def test_project_statuses_are_stable():
    assert [status.value for status in ProjectStatus] == [
        "REQUESTED", "PROVISIONING", "RUNNING", "FAILED", "DELETING", "DELETED"
    ]

def test_project_id_is_namespace():
    project = Project.new(request=make_request(), namespace="demo-api-staging")
    assert project.id == "demo-api-staging"
    assert project.namespace == project.id
```

- [ ] **Step 2: Run the domain tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_domain -v`

Expected: FAIL because `app.domain` and `Project.new` do not exist.

- [ ] **Step 3: Implement domain dataclasses and enums**

```python
class PlatformAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    RECOVERING = "RECOVERING"
    UNAVAILABLE = "UNAVAILABLE"

@dataclass(slots=True)
class Project:
    id: str
    namespace: str
    service_name: str
    environment: str
    image: str
    replicas: int
    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str
    expose_external: bool
    ingress_host: str | None
    status: ProjectStatus
    error_message: str | None
    capacity_claimed: bool
    created_at: datetime
    updated_at: datetime
```

Move the enum definitions out of SQLAlchemy `models.py`. Keep Pydantic response field names unchanged except for string IDs.

- [ ] **Step 4: Update frontend types and failing API expectations**

```typescript
export interface Project {
  id: string
  namespace: string
  status: ProjectStatus
}

export interface AuditLog {
  id: string
  project_id: string
}
```

Change API tests to call `getProject('demo-api-staging')` and expect URL-encoded Namespace paths.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_domain -v`

Run: `npm test -- --run src/api.test.ts` from `frontend`

Expected: all focused tests PASS.

- [ ] **Step 6: Commit the domain boundary**

```powershell
git add backend/app/domain.py backend/app/schemas.py backend/tests/test_domain.py frontend/src/lib/types.ts frontend/src/api.test.ts
git commit -m "refactor: define Firestore-ready project domain"
```

### Task 2: Repository Protocol과 테스트용 InMemory Repository

**Files:**
- Create: `backend/app/repositories/__init__.py`
- Create: `backend/app/repositories/base.py`
- Create: `backend/app/repositories/memory.py`
- Test: `backend/tests/test_memory_repository.py`

**Interfaces:**
- Consumes: `Project`, `AuditLog`, `ProjectStatus`
- Produces: `ProjectRepository` Protocol
- Produces: `ProjectAlreadyExists`, `DemoCapacityExceeded`, `ProjectNotFound`
- Produces: `InMemoryProjectRepository`

- [ ] **Step 1: Write failing repository contract tests**

```python
def test_claim_capacity_and_create_is_atomic():
    repository = InMemoryProjectRepository(max_active_projects=1)
    project = make_project("demo-one-staging")
    repository.claim_capacity_and_create(project)
    with self.assertRaises(DemoCapacityExceeded):
        repository.claim_capacity_and_create(make_project("demo-two-staging"))

def test_release_capacity_is_idempotent():
    repository = seeded_repository(capacity_claimed=True)
    repository.release_capacity("demo-one-staging")
    repository.release_capacity("demo-one-staging")
    self.assertEqual(repository.active_count, 0)
```

- [ ] **Step 2: Run repository tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_memory_repository -v`

Expected: FAIL because repository modules do not exist.

- [ ] **Step 3: Define the exact Repository Protocol**

Define `ProjectRepository` as a `Protocol` with these exact signatures:

- `claim_capacity_and_create(project: Project) -> Project`
- `get_project(project_id: str) -> Project | None`
- `list_projects() -> list[Project]`
- `save_project(project: Project) -> Project`
- `release_capacity(project_id: str) -> Project`
- `append_audit_log(log: AuditLog) -> AuditLog`
- `list_audit_logs(project_id: str) -> list[AuditLog]`
- `health_check() -> dict[str, str]`

- [ ] **Step 4: Implement the InMemory Repository with locking**

Use `threading.RLock` so capacity claim, duplicate check, create, and release are atomic in tests. Return defensive dataclass copies so callers cannot mutate stored state without `save_project`.

- [ ] **Step 5: Run contract tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_memory_repository -v`

Expected: duplicate, capacity, ordering, audit ordering, and idempotent release tests PASS.

- [ ] **Step 6: Commit the repository contract**

```powershell
git add backend/app/repositories backend/tests/test_memory_repository.py
git commit -m "feat: add project repository contract"
```

### Task 3: Firestore Repository와 용량 트랜잭션

**Files:**
- Create: `backend/app/repositories/firestore.py`
- Create: `backend/tests/test_firestore_repository.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py`

**Interfaces:**
- Consumes: `ProjectRepository`
- Produces: `FirestoreProjectRepository(client: firestore.Client, max_active_projects: int)`
- Uses collections: `projects`, `system/demoCapacity`, `projects/{id}/auditLogs`

- [ ] **Step 1: Add the pinned Firestore dependency and settings tests**

Add the current compatible pinned `google-cloud-firestore` version selected by `pip index versions google-cloud-firestore` and add:

```python
firestore_project_id: str = ""
firestore_database: str = "(default)"
repository_backend: Literal["firestore", "memory"] = "firestore"
```

Test that `APP_ENV=testing` with `REPOSITORY_BACKEND=memory` does not construct a Google client.

- [ ] **Step 2: Write failing Firestore mapping and transaction tests**

Implement these exact tests with the fake client:

- `test_project_round_trip_preserves_status_and_utc_timestamps`: save a `RUNNING` project and assert every field after reading it back.
- `test_claim_transaction_rejects_duplicate_document`: seed the same document ID and assert `ProjectAlreadyExists` without changing `active_count`.
- `test_claim_transaction_rejects_fourth_active_project`: seed `active_count=3`, assert `DemoCapacityExceeded`, and assert no fourth document.
- `test_release_transaction_decrements_only_when_claimed`: release twice and assert the count changes from 1 to 0 only once.
- `test_audit_logs_are_ordered_by_created_at_then_id`: seed equal timestamps with IDs `b` and `a`, plus a later log, and assert order `a`, `b`, later.

Use a fake client implementing document, collection, transaction, get, set, and stream behavior. Do not call production Firestore in unit tests.

- [ ] **Step 3: Run Firestore tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_firestore_repository -v`

Expected: FAIL because `FirestoreProjectRepository` is missing.

- [ ] **Step 4: Implement document mapping and transactional capacity**

```python
@firestore.transactional
def _claim(transaction, project_ref, capacity_ref, project_data, max_active):
    if project_ref.get(transaction=transaction).exists:
        raise ProjectAlreadyExists(project_data["id"])
    snapshot = capacity_ref.get(transaction=transaction)
    active = snapshot.get("active_count") if snapshot.exists else 0
    if active >= max_active:
        raise DemoCapacityExceeded(max_active)
    transaction.set(project_ref, project_data)
    transaction.set(capacity_ref, {
        "active_count": active + 1,
        "max_active_projects": max_active,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)
```

Implement release as a separate transaction that checks `capacity_claimed` before decrementing and updates both documents atomically.

- [ ] **Step 5: Run Firestore and repository tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_firestore_repository backend.tests.test_memory_repository -v`

Expected: all repository tests PASS.

- [ ] **Step 6: Commit the Firestore persistence adapter**

```powershell
git add backend/requirements.txt backend/app/config.py backend/app/repositories/firestore.py backend/tests/test_firestore_repository.py
git commit -m "feat: persist portal projects in Firestore"
```

### Task 4: 프로젝트 서비스로 생명주기 orchestration 이동

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/project_service.py`
- Modify: `backend/app/audit.py`
- Modify: `backend/app/routers/projects.py`
- Test: `backend/tests/test_project_service.py`

**Interfaces:**
- Consumes: `ProjectRepository`, existing Kubernetes resource functions
- Produces: `ProjectService.create_project`, `sync_status`, `delete_project`
- Produces: `GkeUnavailable`, `InvalidLifecycleOperation`

- [ ] **Step 1: Write failing lifecycle service tests**

Implement these exact tests with `InMemoryProjectRepository` and a `MagicMock` Kubernetes gateway:

- Successful create asserts final `RUNNING`, `capacity_claimed=true`, resource calls in Namespace → Quota → Deployment → Service → optional Ingress order, and audit actions through `PROJECT_RUNNING`.
- Deployment failure asserts `FAILED`, stored error detail, one capacity release, and `DEPLOYMENT_CREATE_FAILED`.
- Successful delete asserts `DELETING` was persisted before GKE calls, reverse resource order, final `DELETED`, and one capacity release.
- Partial delete failure asserts final `FAILED`, `capacity_claimed=true`, and `PROJECT_DELETE_FAILED`.
- Sync of a `DELETED` project asserts no Kubernetes call and no state change.

Assert both final project state and exact audit action order.

- [ ] **Step 2: Run service tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_project_service -v`

Expected: FAIL because `ProjectService` is missing.

- [ ] **Step 3: Implement ProjectService with injected collaborators**

Define `ProjectService` with constructor arguments `repository: ProjectRepository`, `kubernetes: KubernetesGateway`, `platform_status: PlatformStatusService`, and `settings: Settings`. Its public methods are `create_project(request: ProjectCreateRequest) -> Project`, `sync_status(project_id: str) -> Project`, and `delete_project(project_id: str) -> Project`.

Move lifecycle mutation and audit action ordering out of Router functions. Keep Pod/Event status derivation pure and unit tested.

- [ ] **Step 4: Replace SQLAlchemy audit writes with Repository writes**

```python
def create_audit_log(repository: ProjectRepository, project_id: str,
                     action: str, status: str, message: str | None = None) -> AuditLog:
    return repository.append_audit_log(AuditLog.new(project_id, action, status, message))
```

- [ ] **Step 5: Run service tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_project_service -v`

Expected: lifecycle, failure, idempotency, and capacity tests PASS.

- [ ] **Step 6: Commit the application service boundary**

```powershell
git add backend/app/services backend/app/audit.py backend/app/routers/projects.py backend/tests/test_project_service.py
git commit -m "refactor: isolate project lifecycle service"
```

### Task 5: Cloud Run용 GKE IAM 인증과 플랫폼 상태 판정

**Files:**
- Create: `backend/app/k8s_auth.py`
- Create: `backend/app/services/platform_status.py`
- Modify: `backend/app/k8s_client.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_k8s_auth.py`
- Test: `backend/tests/test_platform_status.py`

**Interfaces:**
- Produces: `build_api_client(settings: Settings) -> client.ApiClient`
- Produces: `PlatformStatusService.get_status() -> PlatformStatus`
- `PlatformStatus` fields: `status`, `message`, `creation_allowed`, `checked_at`

- [ ] **Step 1: Write failing authentication selection tests**

Implement three tests: local mode must call `config.load_kube_config(context="kind-portal-dev")`; GKE mode must call `google.auth.default` and configure the exact DNS host; a forced expired credential must refresh and replace the bearer token before the next Kubernetes request.

Settings must include `kube_auth_mode: Literal["local", "gke"]`, `gke_cluster_location`, `gke_cluster_name`, and `gke_dns_endpoint`.

- [ ] **Step 2: Run auth tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_k8s_auth -v`

Expected: FAIL because `k8s_auth` is missing.

- [ ] **Step 3: Implement local and GKE authentication without key files**

Use `google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])`, refresh with `google.auth.transport.requests.Request`, configure the DNS endpoint and CA data returned from the Container API, and inject a refresh hook before Kubernetes calls. Do not read `GOOGLE_APPLICATION_CREDENTIALS` in application code.

- [ ] **Step 4: Write failing platform availability tests**

Implement four tests using Kubernetes node objects: one Ready schedulable Spot node yields `AVAILABLE`; zero Ready nodes yields `RECOVERING`; `ApiException(401)` and connection exceptions yield `UNAVAILABLE`; a Ready node with a general-workload-blocking `NoSchedule` taint does not count as available capacity.

- [ ] **Step 5: Implement Ready and schedulable node evaluation**

Count nodes only when `spec.unschedulable` is false, the Ready condition is `True`, and no `NoSchedule` taint excludes general workloads. Return `creation_allowed=True` only for `AVAILABLE`.

- [ ] **Step 6: Run auth and platform tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_k8s_auth backend.tests.test_platform_status -v`

Expected: all focused tests PASS.

- [ ] **Step 7: Commit GKE external authentication and availability**

```powershell
git add backend/app/k8s_auth.py backend/app/k8s_client.py backend/app/services/platform_status.py backend/app/config.py backend/tests/test_k8s_auth.py backend/tests/test_platform_status.py
git commit -m "feat: detect GKE availability from Cloud Run"
```

### Task 6: Firestore-backed FastAPI와 오류 계약

**Files:**
- Create: `backend/app/dependencies.py`
- Create: `backend/app/routers/platform.py`
- Modify: `backend/app/routers/projects.py`
- Modify: `backend/app/main.py`
- Delete: `backend/app/db.py`
- Delete: `backend/app/models.py`
- Replace: `backend/tests/test_projects.py`
- Delete: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `GET /api/platform-status`
- Produces: `GKE_UNAVAILABLE` JSON error contract
- Produces: `/health` with independent Firestore and GKE dependency fields

- [ ] **Step 1: Write failing API tests with dependency overrides**

Implement API tests with FastAPI dependency overrides and `TestClient`: list projects returns seeded Firestore data while GKE is unavailable; create and Pod reads return 503 with `GKE_UNAVAILABLE`; platform status returns `RECOVERING` and `creation_allowed=false`; health returns HTTP 200 when Firestore is healthy and reports GKE separately as unavailable.

Expected error body:

```json
{"error":{"code":"GKE_UNAVAILABLE","message":"GKE 상태를 일시적으로 확인할 수 없습니다.","detail":"Kubernetes API connection failed"}}
```

- [ ] **Step 2: Run API tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m unittest backend.tests.test_projects -v`

Expected: FAIL because routers still require SQLAlchemy sessions.

- [ ] **Step 3: Implement dependency injection and thin Routers**

Define dependency functions with these exact signatures: `get_repository() -> ProjectRepository`, `get_project_service(repository: ProjectRepository = Depends(get_repository)) -> ProjectService`, and `get_platform_status_service() -> PlatformStatusService`.

Map domain exceptions to 404, 409, and 503 at the HTTP boundary. URL-decode and validate Namespace IDs through FastAPI path parameters.

- [ ] **Step 4: Replace startup and health behavior**

Remove database table creation, DB retry, SQLAlchemy imports, and MariaDB health checks. Firestore health must perform a bounded document read. GKE status remains informational and must not change `/health` HTTP 200 when Firestore is healthy.

- [ ] **Step 5: Remove SQL dependencies after all imports are gone**

Remove `SQLAlchemy` and `PyMySQL` from `requirements.txt`, delete `db.py`, `models.py`, and DB retry tests. Verify with:

Run: `rg -n "sqlalchemy|pymysql|SessionLocal|Depends\(get_db\)|DB_STARTUP" backend`

Expected: no application matches.

- [ ] **Step 6: Run the backend suite and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v`

Run: `backend\.venv\Scripts\python.exe -m compileall backend/app`

Expected: all tests PASS and compilation succeeds.

- [ ] **Step 7: Commit the Firestore API cutover**

```powershell
git add backend
git commit -m "feat: serve portal API from Firestore"
```

### Task 7: Frontend 문자열 라우팅과 읽기 전용 재시도

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/pages/ProjectList.tsx`
- Modify: `frontend/src/pages/ProjectDetail.tsx`
- Modify: `frontend/src/pages/NewProject.tsx`
- Test: `frontend/src/api.test.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: `getPlatformStatus() -> Promise<PlatformStatus>`
- Uses string project IDs in all API calls and routes
- GET retry policy: 3 total attempts, delays 250 ms then 1000 ms, only network/502/503/504

- [ ] **Step 1: Write failing retry and string route tests**

```typescript
it('retries a GET after a transient 503 and then succeeds', async () => { /* 503, 200 */ })
it('does not retry createProject after a transient failure', async () => { /* one POST */ })
it('encodes namespace IDs in project URLs', async () => { /* demo-api-staging */ })
```

- [ ] **Step 2: Run frontend API tests and verify RED**

Run: `npm test -- --run src/api.test.ts` from `frontend`

Expected: FAIL because retry policy and string IDs are missing.

- [ ] **Step 3: Implement method-aware retry**

```typescript
const readRetryDelays = [250, 1000]

function isTransientReadError(error: unknown): boolean {
  if (!axios.isAxiosError(error)) return false
  return !error.response || [502, 503, 504].includes(error.response.status)
}
```

Retry only `GET`; keep `POST` and `DELETE` single-attempt. Use `baseURL: import.meta.env.VITE_API_BASE_URL ?? ''` and retain existing `/api/...` paths so Firebase Hosting uses same-origin rewrites.

- [ ] **Step 4: Convert routes and query keys to string Namespace IDs**

Remove `Number(id)` and `Number.isFinite`. Use `const projectId = id ?? ''` with `enabled: projectId.length > 0`. Use `encodeURIComponent` inside API functions.

- [ ] **Step 5: Run focused frontend tests and verify GREEN**

Run: `npm test -- --run src/api.test.ts src/App.test.tsx` from `frontend`

Expected: all focused tests PASS.

- [ ] **Step 6: Commit frontend API compatibility**

```powershell
git add frontend/src/lib frontend/src/pages frontend/src/api.test.ts frontend/src/App.test.tsx
git commit -m "feat: use namespace project IDs in frontend"
```

### Task 8: 플랫폼 복구 배너와 작업 차단 UX

**Files:**
- Create: `frontend/src/hooks/usePlatformStatus.ts`
- Create: `frontend/src/components/PlatformStatusBanner.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/NewProject.tsx`
- Modify: `frontend/src/pages/ProjectDetail.tsx`
- Modify: `frontend/src/App.css`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `getPlatformStatus`
- Produces: polling interval 15,000 ms
- Produces: `PlatformStatusBanner` and action disable rules

- [ ] **Step 1: Write failing UI state tests**

Implement four Testing Library cases with fake timers and mocked API functions: `RECOVERING` shows the Korean recovery banner and disables create; a `GKE_UNAVAILABLE` Pod response leaves project and audit text visible; `UNAVAILABLE` disables delete/sync while `RECOVERING` enables them; advancing 15 seconds and returning `AVAILABLE` removes the banner.

- [ ] **Step 2: Run UI tests and verify RED**

Run: `npm test -- --run src/App.test.tsx` from `frontend`

Expected: FAIL because platform polling and banner do not exist.

- [ ] **Step 3: Implement polling hook and accessible banner**

```typescript
export function usePlatformStatus() {
  return useQuery({
    queryKey: ['platform-status'],
    queryFn: getPlatformStatus,
    refetchInterval: 15_000,
  })
}
```

Use `role="status"` for `RECOVERING` and `role="alert"` for `UNAVAILABLE`. Render the server-provided checked time and message.

- [ ] **Step 4: Apply exact action rules**

- Disable create unless status is `AVAILABLE`.
- Allow delete and sync in `RECOVERING`.
- Disable delete and sync in `UNAVAILABLE`.
- Convert `GKE_UNAVAILABLE` Pod/Event errors to an inline “일시적으로 확인할 수 없음” notice without hiding project and audit data.

- [ ] **Step 5: Run full frontend verification**

Run: `npm test` from `frontend`

Run: `npm run lint` from `frontend`

Run: `npm run build` from `frontend`

Expected: tests, lint, and production build PASS.

- [ ] **Step 6: Commit the recovery UX**

```powershell
git add frontend/src
git commit -m "feat: show GKE recovery state in portal"
```

### Task 9: Local development, emulator verification, and living migration record

**Files:**
- Create: `firebase.json`
- Create: `.firebaserc.example`
- Create: `backend/tests/integration/test_firestore_emulator.py`
- Modify: `backend/.env.example`
- Modify: `frontend/.env.example`
- Modify: `README.md`
- Create: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Create: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`

**Interfaces:**
- Produces: local Firestore emulator workflow
- Produces: sanitized chronological work log and blog draft

- [ ] **Step 1: Add failing Firestore emulator integration test**

Implement `FirestoreEmulatorIntegrationTest` with two concrete cases: submit four unique projects through `ThreadPoolExecutor(max_workers=4)` and assert exactly three results plus one `DemoCapacityExceeded`; write one project and two audit logs, construct a new repository instance, then assert the complete project round trip and chronological audit order.

Skip only when `FIRESTORE_EMULATOR_HOST` is absent; the explicit emulator command must run it.

- [ ] **Step 2: Configure Firebase emulators and Hosting public directory**

Use `frontend/dist` as Hosting public output. Add a Firestore emulator on `127.0.0.1:8085`; do not add permissive production client rules because Firestore is accessed only from Cloud Run Admin credentials.

- [ ] **Step 3: Run emulator integration tests**

Run:

```powershell
firebase emulators:exec --only firestore "backend\.venv\Scripts\python.exe -m unittest backend.tests.integration.test_firestore_emulator -v"
```

Expected: concurrent claims yield exactly three successes and one `DemoCapacityExceeded`; round trip PASS.

- [ ] **Step 4: Document local run commands**

Document `REPOSITORY_BACKEND=memory` for fast unit development and Firestore emulator variables for integration. Remove MariaDB as a required serverless-path dependency but retain the legacy GKE rollback documentation.

- [ ] **Step 5: Start the migration log and blog draft with verified facts**

The log must include date/time, commit IDs, tests run, result summaries, and sanitized errors. The blog draft must include the original Spot/MariaDB incident, DB retry mitigation, approved target architecture, state-model separation, and rollback strategy. Do not include secrets, tokens, project numbers, or password output.

- [ ] **Step 6: Commit local workflow and documentation**

```powershell
git add firebase.json .firebaserc.example backend/.env.example frontend/.env.example backend/tests/integration README.md docs/migration
git commit -m "docs: add serverless portal migration workflow"
```

### Task 10: Application phase verification checkpoint

**Files:**
- Modify: `docs/migration/firebase-cloud-run-firestore-migration-log.md`
- Modify: `docs/migration/firebase-cloud-run-firestore-blog-draft.md`

**Interfaces:**
- Produces: a deployable application artifact accepted by the infrastructure plan

- [ ] **Step 1: Run complete backend verification from a clean environment**

Run:

```powershell
backend\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
backend\.venv\Scripts\python.exe -m compileall backend/app
```

Expected: all tests PASS and compilation succeeds.

- [ ] **Step 2: Run complete frontend verification**

Run from `frontend`:

```powershell
npm test
npm run lint
npm run build
```

Expected: all commands exit 0 and `frontend/dist/index.html` exists.

- [ ] **Step 3: Build and run the Cloud Run-compatible container locally**

```powershell
docker build -t portal-backend:firestore-local backend
docker run --rm -d --name portal-backend-firestore-test -p 8080:8080 -e PORT=8080 -e REPOSITORY_BACKEND=memory -e KUBE_AUTH_MODE=local portal-backend:firestore-local
curl.exe -fsS http://127.0.0.1:8080/health
docker stop portal-backend-firestore-test
```

Expected: container listens on `$PORT=8080` and health returns HTTP 200.

- [ ] **Step 4: Record evidence and commit only documentation changes**

Record command versions, test counts, image name, health response summary, and any resolved failures.

```powershell
git add docs/migration
git commit -m "docs: record serverless application verification"
```

- [ ] **Step 5: Stop at the infrastructure approval checkpoint**

Do not enable APIs, create Firestore, change IAM, enable the GKE DNS endpoint, or deploy Cloud Run until the application phase is reviewed and the infrastructure phase is explicitly started.
