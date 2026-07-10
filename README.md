# Kubernetes 기반 Private Cloud Self-Service Portal

## 개요

개발자가 Kubernetes YAML을 직접 작성하지 않고 API를 통해 표준화된 방식으로 배포 리소스를 요청하고 상태를 확인할 수 있는 Private Cloud Self-Service Portal MVP입니다.

## 현재 구현 범위

- FastAPI 백엔드 기본 구성
- MariaDB 로컬 개발환경
- kind 기반 로컬 Kubernetes 클러스터 설정
- `/health` API를 통한 DB/Kubernetes 연결 확인

## 기술 스택

- Backend: Python, FastAPI
- Database: MariaDB
- Kubernetes: kind, kubernetes Python client
- Infra: Docker Compose
- Future: React, TypeScript, Helm, ArgoCD

## 로컬 실행 방법

### 1. MariaDB 실행

```bash
docker compose -f infra/docker-compose.yml up -d
```

### 2. kind 클러스터 생성

```bash
kind create cluster --config infra/kind/kind-config.yaml
```

### 3. Backend 환경변수 설정

```bash
cd backend
cp .env.example .env
```

### 4. Python 가상환경 및 패키지 설치

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell에서는 다음을 사용합니다.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 5. FastAPI 실행

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 6. Health Check

http://127.0.0.1:8000/health

## 다음 개발 계획

- 프로젝트 요청 API
- DB 모델 및 마이그레이션
- Namespace 생성 기능
- Deployment/Service 생성 기능
- Pod 상태 조회 기능

## Phase 2: Project Request API and Namespace Provisioning

This phase adds the first self-service project request flow:

- `POST /api/projects` stores a project request in MariaDB and creates a Kubernetes Namespace.
- `GET /api/projects` returns project requests ordered by newest first.
- `GET /api/projects/{id}` returns one project request by database id.
- The current Kubernetes scope is Namespace creation only. Deployment, Service, Ingress, and ResourceQuota are planned for later phases.

### API Test Example

PowerShell:

```powershell
$body = @{
  service_name = "demo-api"
  environment = "staging"
  image = "nginx:latest"
  replicas = 1
  cpu_request = "100m"
  cpu_limit = "500m"
  memory_request = "128Mi"
  memory_limit = "512Mi"
  expose_external = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/projects" `
  -ContentType "application/json" `
  -Body $body
```

List projects:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/projects"
```

Get one project:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/projects/1"
```

### Kubernetes Verification

```bash
kubectl get namespaces
kubectl get namespace demo-api-staging --show-labels
```

Expected labels include:

- `app.kubernetes.io/managed-by=self-service-portal`
- `app.kubernetes.io/name=demo-api`
- `platform.io/environment=staging`
- `platform.io/project-id=<projects.id>`

### Database Verification

```bash
docker exec -it portal-mariadb mariadb -u portal_user -p
USE portal_db;
SHOW TABLES;
SELECT id, service_name, environment, namespace, status, error_message FROM projects;
```

## Phase 3: Deployment / Service Provisioning

This phase extends project provisioning beyond Namespace creation:

- `POST /api/projects` now creates Namespace, Deployment, and Service in sequence.
- Deployment uses the requested image, replica count, CPU request/limit, and memory request/limit.
- A ClusterIP Service is created as `{service_name}-svc` on port `80`.
- `GET /api/projects/{project_id}/pods` returns Pod phase, Pod IP, node name, start time, container readiness, restart count, state, reason, and message.
- Bad image deployments can be diagnosed through the Pod API. For example, an image pull failure can surface as a waiting container with `ImagePullBackOff`.

### Phase 3 API Test Example

PowerShell:

```powershell
$body = @{
  service_name = "demo-web"
  environment = "staging"
  image = "nginx:latest"
  replicas = 1
  cpu_request = "100m"
  cpu_limit = "500m"
  memory_request = "128Mi"
  memory_limit = "512Mi"
  expose_external = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/projects" `
  -ContentType "application/json" `
  -Body $body
```

Check Kubernetes resources:

```bash
kubectl get all -n demo-web-staging
```

Check Pod status through the API:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/projects/2/pods"
```

### Bad Image Test Example

Use a project request such as:

```powershell
$body = @{
  service_name = "bad-image"
  environment = "staging"
  image = "nginx-not-exist-abc:latest"
  replicas = 1
  expose_external = $false
} | ConvertTo-Json
```

After the Deployment is created, inspect Pods:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/projects/3/pods"
```

The project can be `RUNNING` because Kubernetes accepted the resources, while the Pod API reveals container waiting reasons such as `ImagePullBackOff`.

## Phase 4: Kubernetes Event 조회 API

This phase adds project-scoped Kubernetes Event lookup for operational troubleshooting:

- `GET /api/projects/{project_id}/events` API added.
- Kubernetes Events are listed from the project's Namespace.
- Namespace-wide Events are filtered down to resources related to the project.
- Event `type`, `reason`, `message`, and `count` are returned.
- `involved_object_kind` and `involved_object_name` are returned.
- `first_timestamp`, `last_timestamp`, and `event_time` are returned as ISO strings when present.
- `source_component` is returned when Kubernetes provides it.
- Bad image deployments can now show related Failed, BackOff, ErrImagePull, and ImagePullBackOff event history.

The Pod status API shows the current container state. The Event lookup API shows the history Kubernetes recorded while scheduling resources, pulling images, and creating or starting containers. This makes issues such as ImagePullBackOff easier to analyze in more detail.

### Phase 4 API Test Example

PowerShell Event lookup:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/projects/3/events"
```

Limit the number of returned Events:

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:8000/api/projects/3/events?limit=20"
```

Compare with kubectl:

```bash
kubectl get events -n bad-image-staging --sort-by=.lastTimestamp
```

Bad image project request example:

```powershell
$body = @{
  service_name = "event-fail"
  environment = "staging"
  image = "nginx-not-exist-xyz:latest"
  replicas = 1
  expose_external = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/projects" `
  -ContentType "application/json" `
  -Body $body
```
