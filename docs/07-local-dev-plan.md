# 07. 로컬 개발환경 구성 계획

## 1. 문서 목적

이 문서는 Kubernetes 기반 Private Cloud Self-Service Portal을 로컬에서 개발하고 테스트하기 위한 환경 구성 계획을 정의한다.

목표는 GCP GKE에 매번 연결하지 않고도, Docker와 kind를 사용해 작은 Kubernetes 클러스터에서 빠르게 기능을 검증하는 것이다.

## 2. 로컬 구성 개요

```text
Local Machine
├── Docker Desktop
│   ├── MariaDB Container
│   └── kind Kubernetes Cluster
├── FastAPI Backend
├── React Frontend
├── kubectl
└── kind CLI
```

요청 흐름:

```text
Browser
 → React dev server
 → FastAPI backend
 → Kubernetes Python client
 → kind Kubernetes API Server
 → Namespace / Deployment / Service / Ingress 생성
```

## 3. 필수 설치 도구

| 도구 | 목적 |
|---|---|
| Docker Desktop | MariaDB와 kind 클러스터 실행 |
| kind | Docker 기반 로컬 Kubernetes 클러스터 생성 |
| kubectl | Kubernetes 리소스 확인/디버깅 |
| Python 3.11+ | FastAPI 백엔드 실행 |
| Node.js 20+ | React 프론트엔드 실행 |
| Git | 형상관리 |
| Make 선택 | 반복 명령어 자동화 |

## 4. 권장 디렉토리 구조

```text
private-cloud-self-service-portal
├── backend
│   ├── app
│   ├── tests
│   ├── alembic
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend
│   ├── src
│   ├── package.json
│   └── Dockerfile
│
├── infra
│   ├── docker-compose.yml
│   ├── kind
│   │   └── kind-config.yaml
│   ├── scripts
│   │   ├── create-kind-cluster.sh
│   │   ├── delete-kind-cluster.sh
│   │   └── install-ingress-nginx.sh
│   └── k8s-samples
│
├── docs
│   ├── 01-one-pager.md
│   ├── 02-prd.md
│   ├── 03-architecture.md
│   ├── 04-k8s-resource-design.md
│   ├── 05-api-spec.md
│   ├── 06-db-model.md
│   └── 07-local-dev-plan.md
│
└── README.md
```

## 5. Docker Compose 구성 계획

초기에는 MariaDB만 Docker Compose로 실행한다. FastAPI와 React는 로컬 개발 서버로 실행해 빠른 피드백을 얻는다.

### docker-compose.yml 초안

```yaml
version: "3.9"

services:
  mariadb:
    image: mariadb:11
    container_name: portal-mariadb
    environment:
      MARIADB_DATABASE: portal_db
      MARIADB_USER: portal_user
      MARIADB_PASSWORD: portal_password
      MARIADB_ROOT_PASSWORD: root_password
    ports:
      - "3306:3306"
    volumes:
      - portal_mariadb_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  portal_mariadb_data:
```

## 6. kind 클러스터 구성

### kind-config.yaml 초안

```yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: portal-dev
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 80
        hostPort: 8080
        protocol: TCP
      - containerPort: 443
        hostPort: 8443
        protocol: TCP
```

### 클러스터 생성

```bash
kind create cluster --config infra/kind/kind-config.yaml
kubectl cluster-info --context kind-portal-dev
kubectl get nodes
```

### 클러스터 삭제

```bash
kind delete cluster --name portal-dev
```

## 7. NGINX Ingress Controller 설치

Ingress 기능은 MVP 2부터 사용한다.

설치 예시:

```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=120s
```

검증:

```bash
kubectl get pods -n ingress-nginx
kubectl get ingressclass
```

## 8. 백엔드 환경변수

`.env` 예시:

```env
APP_ENV=local
APP_PORT=8000

DB_HOST=localhost
DB_PORT=3306
DB_NAME=portal_db
DB_USER=portal_user
DB_PASSWORD=portal_password

KUBE_CONFIG_PATH=~/.kube/config
KUBE_CONTEXT=kind-portal-dev

DEFAULT_CONTAINER_PORT=80
DEFAULT_REPLICAS=1
DEFAULT_CPU_REQUEST=250m
DEFAULT_CPU_LIMIT=500m
DEFAULT_MEMORY_REQUEST=256Mi
DEFAULT_MEMORY_LIMIT=512Mi

CORS_ALLOWED_ORIGINS=http://localhost:5173
```

## 9. 백엔드 실행 계획

### Python 가상환경

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 예시:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### requirements.txt 초안

```text
fastapi
uvicorn[standard]
sqlalchemy
alembic
pymysql
python-dotenv
pydantic-settings
kubernetes
pytest
httpx
```

### 실행

```bash
uvicorn app.main:app --reload --port 8000
```

검증:

```bash
curl http://localhost:8000/health
```

## 10. 프론트엔드 실행 계획

### 생성

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install @tanstack/react-query axios react-router-dom
```

### 실행

```bash
npm run dev
```

접속:

```text
http://localhost:5173
```

## 11. DB 마이그레이션 계획

### Alembic 초기화

```bash
cd backend
alembic init alembic
```

### 마이그레이션 실행

```bash
alembic revision --autogenerate -m "create initial tables"
alembic upgrade head
```

검증:

```bash
mysql -h 127.0.0.1 -P 3306 -u portal_user -p portal_db
SHOW TABLES;
```

## 12. Kubernetes 연결 검증

### kubectl 검증

```bash
kubectl config current-context
kubectl get nodes
kubectl get namespaces
```

### FastAPI에서 검증할 기능

초기 테스트 API:

```text
GET /health
```

응답 예시:

```json
{
  "status": "UP",
  "database": "UP",
  "kubernetes": "UP",
  "current_context": "kind-portal-dev"
}
```

## 13. 개발 순서

### Step 1. 환경 기반 확인

```text
Docker Desktop 실행
MariaDB 컨테이너 실행
kind cluster 생성
kubectl get nodes 성공
FastAPI /health 성공
React dev server 실행
```

### Step 2. DB 기반 API 개발

```text
projects 테이블 생성
POST /api/projects DB 저장
GET /api/projects 조회
GET /api/projects/{id} 조회
```

### Step 3. Kubernetes 연동

```text
Python client로 namespace 목록 조회
Namespace 생성
Deployment 생성
Service 생성
```

### Step 4. 상태 조회

```text
Pod 목록 조회
Pod phase 조회
Event 조회
ImagePullBackOff 재현
```

### Step 5. 운영 기능 추가

```text
ResourceQuota 생성
Ingress 생성
DELETE API 구현
Audit Log 저장
```

## 14. 로컬 테스트 시나리오

### 정상 배포 테스트

```json
{
  "service_name": "demo-api",
  "environment": "staging",
  "image": "nginx:latest",
  "replicas": 1,
  "cpu_request": "100m",
  "cpu_limit": "300m",
  "memory_request": "128Mi",
  "memory_limit": "256Mi",
  "container_port": 80,
  "expose_external": false
}
```

확인 명령:

```bash
kubectl get ns
kubectl get all -n demo-api-staging
kubectl get pods -n demo-api-staging
```

### 실패 배포 테스트

```json
{
  "service_name": "broken-api",
  "environment": "staging",
  "image": "nginx-not-exist:latest",
  "replicas": 1,
  "cpu_request": "100m",
  "cpu_limit": "300m",
  "memory_request": "128Mi",
  "memory_limit": "256Mi",
  "container_port": 80,
  "expose_external": false
}
```

확인 명령:

```bash
kubectl get pods -n broken-api-staging
kubectl describe pod -n broken-api-staging <pod-name>
```

포털에서 확인할 항목:

```text
Pod phase: Pending
Container state: waiting
Waiting reason: ImagePullBackOff
Event message: Failed to pull image
```

### 삭제 테스트

```bash
curl -X DELETE http://localhost:8000/api/projects/1
kubectl get ns demo-api-staging
```

## 15. 자주 발생할 수 있는 문제

### 문제 1. Docker Desktop 메모리 부족

대응:

- kind single-node만 사용
- ArgoCD/Prometheus/Grafana는 초기 제외
- 테스트 Pod 수를 1개로 제한
- Docker Desktop 메모리 할당 확인

### 문제 2. kubeconfig context 오류

증상:

```text
FastAPI가 잘못된 클러스터에 접근
```

확인:

```bash
kubectl config get-contexts
kubectl config current-context
```

대응:

```bash
kubectl config use-context kind-portal-dev
```

### 문제 3. Ingress 접속 실패

원인 후보:

- ingress-nginx 미설치
- kind extraPortMappings 누락
- `/etc/hosts` 설정 누락
- Ingress host 오타

확인:

```bash
kubectl get pods -n ingress-nginx
kubectl get ingress -A
kubectl describe ingress -n demo-api-staging demo-api-ingress
```

### 문제 4. ImagePullBackOff

원인:

- 이미지명 오타
- 태그 없음
- private registry 인증 없음

대응:

- Event message 표시
- 사용자에게 이미지명 확인 안내

### 문제 5. ResourceQuota 초과

원인:

- 요청한 CPU/Memory가 Namespace Quota를 초과

대응:

- Event 조회
- 사용자에게 리소스 제한값 조정 안내

## 16. Makefile 후보

```makefile
.PHONY: db-up db-down kind-up kind-down backend frontend

db-up:
	docker compose -f infra/docker-compose.yml up -d

db-down:
	docker compose -f infra/docker-compose.yml down

kind-up:
	kind create cluster --config infra/kind/kind-config.yaml

kind-down:
	kind delete cluster --name portal-dev

backend:
	cd backend && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev
```

## 17. 완료 기준

로컬 개발환경 구성은 다음 조건을 만족하면 완료로 본다.

1. `docker compose up -d`로 MariaDB가 실행된다.
2. `kind create cluster`로 로컬 Kubernetes 클러스터가 생성된다.
3. `kubectl get nodes`가 성공한다.
4. FastAPI `/health`에서 DB와 Kubernetes 상태가 `UP`으로 표시된다.
5. React 개발 서버가 실행된다.
6. `POST /api/projects` 호출로 kind 클러스터에 Namespace/Deployment/Service가 생성된다.
