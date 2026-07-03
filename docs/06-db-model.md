# 06. DB 모델 초안

## 1. 문서 목적

이 문서는 Self-Service Portal에서 사용할 데이터베이스 모델을 정의한다. DB는 프로젝트 신청 정보, Kubernetes 리소스 메타데이터, 상태 변경 이력, Audit Log를 저장한다.

## 2. DB 선택

MVP에서는 MariaDB를 사용한다.

선택 이유:

- SQL 기반 신청/상태/로그 데이터 관리에 적합하다.
- Docker Compose로 로컬 실행이 쉽다.
- MySQL 계열 문법과 운영 경험을 보여주기 좋다.
- 향후 MySQL 또는 Cloud SQL 계열로 전환하기 쉽다.

## 3. 개념 모델

```text
Project
  ├── ProjectStatusHistory
  ├── K8sResource
  └── AuditLog
```

관계:

- 하나의 Project는 여러 상태 변경 이력을 가진다.
- 하나의 Project는 여러 Kubernetes 리소스 메타데이터를 가진다.
- 하나의 Project는 여러 Audit Log를 가진다.

## 4. 테이블 목록

| 테이블 | 목적 |
|---|---|
| projects | 프로젝트 신청 정보와 현재 상태 저장 |
| project_status_histories | 상태 변경 이력 저장 |
| k8s_resources | 생성된 Kubernetes 리소스 메타데이터 저장 |
| audit_logs | 생성/삭제/오류 등 감사 로그 저장 |

## 5. projects 테이블

### 목적

프로젝트 배포 신청의 핵심 정보와 현재 상태를 저장한다.

### 컬럼

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | 프로젝트 ID |
| service_name | VARCHAR(63) | NOT NULL | 서비스명 |
| environment | VARCHAR(20) | NOT NULL | dev/staging/prod |
| image | VARCHAR(255) | NOT NULL | 컨테이너 이미지 |
| replicas | INT | NOT NULL | Replica 수 |
| cpu_request | VARCHAR(20) | NOT NULL | CPU request |
| cpu_limit | VARCHAR(20) | NOT NULL | CPU limit |
| memory_request | VARCHAR(20) | NOT NULL | Memory request |
| memory_limit | VARCHAR(20) | NOT NULL | Memory limit |
| container_port | INT | NOT NULL DEFAULT 80 | 컨테이너 포트 |
| expose_external | BOOLEAN | NOT NULL DEFAULT FALSE | 외부 공개 여부 |
| namespace | VARCHAR(63) | NOT NULL | Kubernetes Namespace |
| deployment_name | VARCHAR(63) | NULL | Deployment 이름 |
| service_name_k8s | VARCHAR(63) | NULL | Service 이름 |
| ingress_name | VARCHAR(63) | NULL | Ingress 이름 |
| ingress_host | VARCHAR(255) | NULL | Ingress Host |
| status | VARCHAR(40) | NOT NULL | 현재 상태 |
| last_error_code | VARCHAR(100) | NULL | 최근 에러 코드 |
| last_error_message | TEXT | NULL | 최근 에러 메시지 |
| created_at | DATETIME | NOT NULL | 생성 시각 |
| updated_at | DATETIME | NOT NULL | 수정 시각 |
| deleted_at | DATETIME | NULL | 삭제 시각 |

### 인덱스

```sql
CREATE UNIQUE INDEX uq_projects_service_env
ON projects(service_name, environment);

CREATE INDEX idx_projects_status
ON projects(status);

CREATE INDEX idx_projects_namespace
ON projects(namespace);

CREATE INDEX idx_projects_created_at
ON projects(created_at);
```

### 상태값

```text
REQUESTED
VALIDATING
PROVISIONING
RUNNING
FAILED
DELETING
DELETED
```

MVP에서는 `VARCHAR`로 관리하고, 애플리케이션 레벨 enum으로 제한한다.

## 6. project_status_histories 테이블

### 목적

프로젝트 상태 변경 이력을 저장한다.

### 컬럼

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | 이력 ID |
| project_id | BIGINT | FK, NOT NULL | 프로젝트 ID |
| previous_status | VARCHAR(40) | NULL | 이전 상태 |
| current_status | VARCHAR(40) | NOT NULL | 변경 상태 |
| reason | VARCHAR(255) | NULL | 상태 변경 이유 |
| message | TEXT | NULL | 상세 메시지 |
| created_at | DATETIME | NOT NULL | 생성 시각 |

### 인덱스

```sql
CREATE INDEX idx_project_status_histories_project_id
ON project_status_histories(project_id);

CREATE INDEX idx_project_status_histories_created_at
ON project_status_histories(created_at);
```

### 예시 데이터

| project_id | previous_status | current_status | reason |
|---|---|---|---|
| 1 | REQUESTED | PROVISIONING | namespace creation started |
| 1 | PROVISIONING | RUNNING | all pods are ready |
| 2 | PROVISIONING | FAILED | ImagePullBackOff detected |

## 7. k8s_resources 테이블

### 목적

프로젝트별로 생성된 Kubernetes 리소스의 메타데이터를 저장한다.

### 컬럼

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | 리소스 ID |
| project_id | BIGINT | FK, NOT NULL | 프로젝트 ID |
| resource_kind | VARCHAR(40) | NOT NULL | Namespace/Deployment/Service/Ingress/ResourceQuota |
| resource_name | VARCHAR(100) | NOT NULL | 리소스 이름 |
| namespace | VARCHAR(100) | NULL | 리소스 Namespace |
| api_version | VARCHAR(50) | NULL | Kubernetes API version |
| status | VARCHAR(40) | NOT NULL | CREATED/DELETED/FAILED |
| created_at | DATETIME | NOT NULL | 생성 시각 |
| deleted_at | DATETIME | NULL | 삭제 시각 |

### 인덱스

```sql
CREATE INDEX idx_k8s_resources_project_id
ON k8s_resources(project_id);

CREATE INDEX idx_k8s_resources_kind_name
ON k8s_resources(resource_kind, resource_name);

CREATE INDEX idx_k8s_resources_namespace
ON k8s_resources(namespace);
```

### resource_kind 값

```text
NAMESPACE
RESOURCE_QUOTA
DEPLOYMENT
SERVICE
INGRESS
```

### status 값

```text
CREATED
FAILED
DELETING
DELETED
```

## 8. audit_logs 테이블

### 목적

사용자 또는 시스템에 의해 발생한 주요 행위를 기록한다.

### 컬럼

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| id | BIGINT | PK, AUTO_INCREMENT | 로그 ID |
| project_id | BIGINT | FK, NULL | 프로젝트 ID |
| action | VARCHAR(80) | NOT NULL | 액션명 |
| target_type | VARCHAR(40) | NOT NULL | 대상 타입 |
| target_name | VARCHAR(100) | NULL | 대상 이름 |
| result | VARCHAR(20) | NOT NULL | SUCCESS/FAILURE |
| message | TEXT | NULL | 메시지 |
| error_code | VARCHAR(100) | NULL | 에러 코드 |
| error_detail | TEXT | NULL | 상세 에러 |
| created_at | DATETIME | NOT NULL | 생성 시각 |

### 인덱스

```sql
CREATE INDEX idx_audit_logs_project_id
ON audit_logs(project_id);

CREATE INDEX idx_audit_logs_action
ON audit_logs(action);

CREATE INDEX idx_audit_logs_created_at
ON audit_logs(created_at);
```

### action 값 예시

```text
CREATE_PROJECT
CREATE_NAMESPACE
CREATE_RESOURCE_QUOTA
CREATE_DEPLOYMENT
CREATE_SERVICE
CREATE_INGRESS
SYNC_STATUS
DELETE_PROJECT
DELETE_NAMESPACE
STATUS_CHANGE
K8S_ERROR_DETECTED
```

### result 값

```text
SUCCESS
FAILURE
```

## 9. ERD 초안

```text
projects
  id PK
  service_name
  environment
  namespace
  status
      |
      | 1:N
      v
project_status_histories
  id PK
  project_id FK
  previous_status
  current_status

projects
      |
      | 1:N
      v
k8s_resources
  id PK
  project_id FK
  resource_kind
  resource_name

projects
      |
      | 1:N
      v
audit_logs
  id PK
  project_id FK
  action
  result
```

## 10. DDL 초안

```sql
CREATE TABLE projects (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    service_name VARCHAR(63) NOT NULL,
    environment VARCHAR(20) NOT NULL,
    image VARCHAR(255) NOT NULL,
    replicas INT NOT NULL,
    cpu_request VARCHAR(20) NOT NULL,
    cpu_limit VARCHAR(20) NOT NULL,
    memory_request VARCHAR(20) NOT NULL,
    memory_limit VARCHAR(20) NOT NULL,
    container_port INT NOT NULL DEFAULT 80,
    expose_external BOOLEAN NOT NULL DEFAULT FALSE,
    namespace VARCHAR(63) NOT NULL,
    deployment_name VARCHAR(63),
    service_name_k8s VARCHAR(63),
    ingress_name VARCHAR(63),
    ingress_host VARCHAR(255),
    status VARCHAR(40) NOT NULL,
    last_error_code VARCHAR(100),
    last_error_message TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    deleted_at DATETIME,
    CONSTRAINT uq_projects_service_env UNIQUE (service_name, environment)
);

CREATE TABLE project_status_histories (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    previous_status VARCHAR(40),
    current_status VARCHAR(40) NOT NULL,
    reason VARCHAR(255),
    message TEXT,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_status_histories_project
        FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE k8s_resources (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT NOT NULL,
    resource_kind VARCHAR(40) NOT NULL,
    resource_name VARCHAR(100) NOT NULL,
    namespace VARCHAR(100),
    api_version VARCHAR(50),
    status VARCHAR(40) NOT NULL,
    created_at DATETIME NOT NULL,
    deleted_at DATETIME,
    CONSTRAINT fk_k8s_resources_project
        FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE audit_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id BIGINT,
    action VARCHAR(80) NOT NULL,
    target_type VARCHAR(40) NOT NULL,
    target_name VARCHAR(100),
    result VARCHAR(20) NOT NULL,
    message TEXT,
    error_code VARCHAR(100),
    error_detail TEXT,
    created_at DATETIME NOT NULL,
    CONSTRAINT fk_audit_logs_project
        FOREIGN KEY (project_id) REFERENCES projects(id)
);
```

## 11. SQLAlchemy 모델 구조 초안

```text
backend/app/db/models.py
├── Project
├── ProjectStatusHistory
├── K8sResource
└── AuditLog
```

## 12. 마이그레이션 계획

Alembic을 사용한다.

초기 마이그레이션:

```text
001_create_projects
002_create_project_status_histories
003_create_k8s_resources
004_create_audit_logs
```

## 13. 데이터 정합성 고려

### 13.1 DB 저장 성공 후 Kubernetes 생성 실패

처리:

1. projects.status = `FAILED`
2. last_error_code 저장
3. last_error_message 저장
4. audit_logs에 실패 기록
5. project_status_histories에 상태 변경 이력 기록

### 13.2 Kubernetes 생성 성공 후 DB 업데이트 실패

처리:

- 운영급 환경에서는 보상 트랜잭션 또는 재시도 큐가 필요하다.
- MVP에서는 예외 로그를 남기고, 수동 정리 가능하도록 Kubernetes Label을 반드시 부여한다.

### 13.3 삭제 중 일부 실패

처리:

- 삭제 실패 리소스를 audit_logs에 기록한다.
- 프로젝트 상태는 `FAILED` 또는 `DELETING`으로 유지한다.
- 재시도 API는 향후 확장으로 둔다.

## 14. 향후 확장 컬럼

projects 확장 후보:

- owner_user_id
- team_name
- cluster_name
- gitops_enabled
- argocd_application_name
- helm_chart_version
- hpa_enabled
- min_replicas
- max_replicas

별도 테이블 확장 후보:

- users
- teams
- clusters
- gitops_applications
- resource_usage_snapshots
