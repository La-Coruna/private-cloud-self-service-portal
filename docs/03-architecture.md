# 03. 시스템 아키텍처 초안

## 1. 아키텍처 목표

본 프로젝트의 아키텍처 목표는 개발자가 Kubernetes 리소스를 직접 작성하지 않고도 웹/API를 통해 표준화된 방식으로 서비스를 배포하고 운영 상태를 확인할 수 있게 하는 것이다.

핵심 설계 방향은 다음과 같다.

1. 웹/API 기반 셀프서비스 제공
2. Kubernetes 리소스 생성 표준화
3. 신청 정보와 상태 이력의 DB 저장
4. 배포 상태와 실패 원인 조회
5. Direct Apply 방식에서 GitOps 방식으로 확장 가능한 구조
6. 로컬 kind와 GKE 모두에서 동작 가능한 구조

## 2. 전체 구성도

```text
[Developer Browser]
        |
        v
[React + TypeScript Dashboard]
        |
        | REST API
        v
[FastAPI Backend]
        |                         
        | SQLAlchemy              | kubernetes Python client
        v                         v
[MariaDB]                 [Kubernetes API Server]
                                  |
                                  v
                         [kind or GKE Cluster]
                                  |
          ------------------------------------------------
          |              |              |               |
     Namespace     ResourceQuota   Deployment       Service/Ingress
                                  |
                                  v
                                Pods
```

## 3. 로컬 개발 아키텍처

로컬 개발에서는 Kubernetes 클러스터를 GCP에 매번 연결하지 않고, Docker 위에 kind 클러스터를 작게 띄워 테스트한다.

```text
Local Machine
├── Docker Desktop
│   ├── MariaDB Container
│   └── kind Cluster Container
│       └── Kubernetes API Server
├── FastAPI Backend
└── React Frontend
```

요청 흐름:

```text
Browser
 → React dev server
 → FastAPI local server
 → kubeconfig 기반 kind cluster 접근
 → Kubernetes 리소스 생성/조회
```

## 4. GKE 확장 아키텍처

기능 안정화 후에는 GKE 클러스터를 대상으로 동일한 API 흐름을 검증한다.

```text
Developer Browser
        |
        v
[Portal Frontend]
        |
        v
[Portal Backend]
        |
        v
[GKE Kubernetes API Server]
        |
        v
[GKE Cluster]
```

확장 시 포털 자체도 GKE 내부에 배포할 수 있다.

```text
GKE Cluster
├── portal-system namespace
│   ├── self-service-frontend
│   ├── self-service-backend
│   └── mariadb or external Cloud SQL
│
├── demo-api-staging namespace
│   ├── ResourceQuota
│   ├── Deployment
│   ├── Service
│   └── Ingress
│
└── other application namespaces
```

이때 FastAPI 백엔드는 kubeconfig 대신 ServiceAccount와 RBAC를 통해 Kubernetes API에 접근한다.

## 5. 주요 컴포넌트 책임

### 5.1 React Dashboard

역할:

- 프로젝트 생성 폼 제공
- 프로젝트 목록 조회
- 프로젝트 상세 정보 표시
- Pod 상태 표시
- Kubernetes Event 표시
- 삭제 버튼 제공

주요 화면:

- `/projects`: 프로젝트 목록
- `/projects/new`: 프로젝트 생성
- `/projects/:id`: 프로젝트 상세
- `/audit-logs`: Audit Log 목록

### 5.2 FastAPI Backend

역할:

- REST API 제공
- 입력값 검증
- DB 트랜잭션 처리
- Kubernetes 리소스 생성/조회/삭제
- 상태 전이 관리
- Audit Log 저장
- 오류 메시지 변환

내부 모듈 예시:

```text
backend/app
├── api
│   ├── projects.py
│   └── audit_logs.py
├── core
│   ├── config.py
│   └── logging.py
├── db
│   ├── session.py
│   └── models.py
├── schemas
│   └── project.py
├── services
│   ├── project_service.py
│   ├── provisioning_service.py
│   └── k8s_status_service.py
└── k8s
    ├── client.py
    ├── namespace.py
    ├── quota.py
    ├── deployment.py
    ├── service.py
    ├── ingress.py
    └── events.py
```

### 5.3 MariaDB

역할:

- 프로젝트 신청 정보 저장
- 현재 상태 저장
- 상태 변경 이력 저장
- Audit Log 저장
- 생성된 Kubernetes 리소스 이름 저장

### 5.4 Kubernetes Cluster

역할:

- 실제 애플리케이션 워크로드 실행
- Namespace 격리
- ResourceQuota 적용
- Deployment/Pod 실행
- Service 네트워킹 제공
- Ingress 외부 노출 제공
- Event/Pod 상태 제공

## 6. 핵심 요청 흐름

### 6.1 프로젝트 생성 흐름

```text
1. 사용자가 프로젝트 생성 폼 제출
2. React → POST /api/projects 호출
3. FastAPI 입력값 검증
4. projects 테이블에 REQUESTED 상태 저장
5. Namespace 이름 생성
6. Kubernetes Namespace 생성
7. ResourceQuota 생성
8. Deployment 생성
9. Service 생성
10. expose_external=true인 경우 Ingress 생성
11. 상태를 PROVISIONING 또는 RUNNING으로 업데이트
12. Audit Log 기록
13. 프로젝트 상세 응답 반환
```

### 6.2 상태 조회 흐름

```text
1. 사용자가 프로젝트 상세 화면 접근
2. React → GET /api/projects/{id} 호출
3. React → GET /api/projects/{id}/pods 호출
4. React → GET /api/projects/{id}/events 호출
5. FastAPI가 DB에서 프로젝트 정보 조회
6. FastAPI가 Kubernetes API에서 Pod/Event 조회
7. UI에 현재 상태와 실패 원인 표시
```

### 6.3 삭제 흐름

```text
1. 사용자가 삭제 버튼 클릭
2. React → DELETE /api/projects/{id} 호출
3. FastAPI가 프로젝트 상태를 DELETING으로 변경
4. Ingress 삭제
5. Service 삭제
6. Deployment 삭제
7. ResourceQuota 삭제
8. Namespace 삭제
9. 프로젝트 상태를 DELETED로 변경
10. Audit Log 기록
```

## 7. 상태 전이 설계

```text
REQUESTED
  → VALIDATING
  → PROVISIONING_NAMESPACE
  → PROVISIONING_QUOTA
  → PROVISIONING_WORKLOAD
  → RUNNING
  → FAILED
  → DELETING
  → DELETED
```

MVP에서는 구현 복잡도를 낮추기 위해 다음 단순 상태를 먼저 사용한다.

```text
REQUESTED
PROVISIONING
RUNNING
FAILED
DELETING
DELETED
```

이후 `project_status_histories` 테이블을 통해 세부 단계 이력을 저장한다.

## 8. Direct Apply 방식

MVP에서는 FastAPI가 Kubernetes Python client를 사용해 Kubernetes API Server에 직접 리소스를 생성한다.

```text
FastAPI
 → kubernetes Python client
 → Kubernetes API Server
 → Namespace/Deployment/Service/Ingress 생성
```

장점:

- 구현이 빠르다.
- 로컬 kind에서 테스트하기 쉽다.
- Kubernetes API 동작을 직접 이해할 수 있다.

단점:

- Git 기반 변경 이력이 남지 않는다.
- 운영 환경에서는 선언적 관리와 변경 추적이 부족할 수 있다.

## 9. GitOps 확장 방식

향후에는 FastAPI가 Kubernetes에 직접 Apply하지 않고 Git Repository에 Helm values를 생성한 뒤 ArgoCD가 Sync하는 구조로 확장한다.

```text
React
 → FastAPI
 → values.yaml 생성
 → Git Repository commit
 → ArgoCD Sync
 → Kubernetes 반영
```

장점:

- Git 기반 변경 이력 확보
- 선언적 배포 관리
- ArgoCD UI를 통한 Sync 상태 확인
- 롤백과 Diff 확인 가능

## 10. 보안/권한 확장 방향

MVP에서는 로컬 kubeconfig를 사용한다. GKE 또는 클러스터 내부 배포 시에는 다음 구조로 확장한다.

```text
FastAPI Pod
 → ServiceAccount
 → Role/ClusterRole
 → RoleBinding/ClusterRoleBinding
 → Kubernetes API Server
```

권한 원칙:

- 필요한 리소스만 create/get/list/delete 가능
- Secret 조회/수정은 MVP에서 제외
- ClusterRole 생성 권한은 부여하지 않음
- 사용자가 요청한 Namespace와 플랫폼 관리 Label이 붙은 리소스만 제어

## 11. 주요 설계 결정

| 결정 | 내용 | 이유 |
|---|---|---|
| Backend | FastAPI | Python 기반 K8S 자동화와 API 개발을 빠르게 구현 가능 |
| DB | MariaDB | SQL 기반 상태/로그 저장에 적합하고 공고 기술스택과 연결성 높음 |
| Local K8S | kind | Docker 기반으로 가볍고 재현성 좋음 |
| K8S 연동 | kubernetes Python client | kubectl 명령 실행보다 안정적이고 코드 기반 제어 가능 |
| 초기 배포 방식 | Direct Apply | MVP 구현 속도와 학습 효과가 높음 |
| 확장 배포 방식 | Helm + ArgoCD | 운영 환경에서 GitOps와 선언적 배포로 확장 가능 |

## 12. 향후 확장 아키텍처

```text
[React]
   |
[FastAPI]
   |------------------|
   | Direct Apply     | GitOps Apply
   v                  v
[K8S API]        [Git Repo]
                      |
                      v
                  [ArgoCD]
                      |
                      v
                   [K8S API]
```

초기에는 Direct Apply만 구현하고, 문서와 인터페이스 구조는 GitOps 확장이 가능하도록 분리한다.
