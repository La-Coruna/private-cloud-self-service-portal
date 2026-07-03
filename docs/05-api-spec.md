# 05. API 명세서

## 1. 기본 정보

Base URL:

```text
http://localhost:8000/api
```

응답 형식:

```text
application/json
```

인증:

- MVP에서는 인증을 생략한다.
- 향후 JWT 또는 사내 SSO 연동을 고려한다.

## 2. 공통 응답 형식

### 성공 응답 예시

```json
{
  "data": {},
  "message": "success"
}
```

### 에러 응답 예시

```json
{
  "error": {
    "code": "K8S_RESOURCE_CREATE_FAILED",
    "message": "Deployment 생성에 실패했습니다.",
    "detail": "Forbidden: deployments.apps is forbidden"
  }
}
```

## 3. 상태 코드 정책

| HTTP Status | 의미 |
|---|---|
| 200 | 조회/삭제 성공 |
| 201 | 생성 성공 |
| 400 | 입력값 오류 |
| 404 | 리소스 없음 |
| 409 | 중복 리소스 또는 상태 충돌 |
| 422 | 스키마 검증 실패 |
| 500 | 서버 내부 오류 |
| 502 | Kubernetes API 연동 실패 |

## 4. 프로젝트 생성

### `POST /projects`

서비스 배포 신청을 생성하고 Kubernetes 리소스를 생성한다.

### Request Body

```json
{
  "service_name": "demo-api",
  "environment": "staging",
  "image": "nginx:latest",
  "replicas": 2,
  "cpu_request": "250m",
  "cpu_limit": "500m",
  "memory_request": "256Mi",
  "memory_limit": "512Mi",
  "container_port": 80,
  "expose_external": true
}
```

### Request Field

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| service_name | string | Y | 서비스명. 소문자/숫자/하이픈 권장 |
| environment | string | Y | dev, staging, prod 중 하나 |
| image | string | Y | 컨테이너 이미지 |
| replicas | integer | Y | Pod replica 수 |
| cpu_request | string | Y | CPU request |
| cpu_limit | string | Y | CPU limit |
| memory_request | string | Y | Memory request |
| memory_limit | string | Y | Memory limit |
| container_port | integer | N | 기본값 80 |
| expose_external | boolean | Y | Ingress 생성 여부 |

### Response `201 Created`

```json
{
  "data": {
    "id": 1,
    "service_name": "demo-api",
    "environment": "staging",
    "image": "nginx:latest",
    "replicas": 2,
    "namespace": "demo-api-staging",
    "deployment_name": "demo-api-deployment",
    "service_name_k8s": "demo-api-service",
    "ingress_name": "demo-api-ingress",
    "ingress_host": "demo-api.staging.local",
    "status": "PROVISIONING",
    "created_at": "2026-07-03T12:00:00+09:00"
  },
  "message": "project created"
}
```

### Error Cases

| 코드 | 조건 | 설명 |
|---|---|---|
| INVALID_SERVICE_NAME | 서비스명 형식 오류 | 소문자/숫자/하이픈만 허용 |
| INVALID_RESOURCE_VALUE | CPU/Memory 형식 오류 | Kubernetes quantity 형식 오류 |
| PROJECT_ALREADY_EXISTS | 동일 서비스명/환경 존재 | 중복 생성 방지 |
| K8S_NAMESPACE_CREATE_FAILED | Namespace 생성 실패 | Kubernetes API 오류 |
| K8S_DEPLOYMENT_CREATE_FAILED | Deployment 생성 실패 | Kubernetes API 오류 |
| K8S_SERVICE_CREATE_FAILED | Service 생성 실패 | Kubernetes API 오류 |
| K8S_INGRESS_CREATE_FAILED | Ingress 생성 실패 | Kubernetes API 오류 |

## 5. 프로젝트 목록 조회

### `GET /projects`

프로젝트 목록을 조회한다.

### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| environment | string | N | 환경 필터 |
| status | string | N | 상태 필터 |
| page | integer | N | 기본값 1 |
| size | integer | N | 기본값 20 |

### Response `200 OK`

```json
{
  "data": {
    "items": [
      {
        "id": 1,
        "service_name": "demo-api",
        "environment": "staging",
        "image": "nginx:latest",
        "namespace": "demo-api-staging",
        "status": "RUNNING",
        "expose_external": true,
        "created_at": "2026-07-03T12:00:00+09:00",
        "updated_at": "2026-07-03T12:01:30+09:00"
      }
    ],
    "page": 1,
    "size": 20,
    "total": 1
  },
  "message": "success"
}
```

## 6. 프로젝트 상세 조회

### `GET /projects/{project_id}`

프로젝트 신청 정보와 Kubernetes 리소스 메타데이터를 조회한다.

### Response `200 OK`

```json
{
  "data": {
    "id": 1,
    "service_name": "demo-api",
    "environment": "staging",
    "image": "nginx:latest",
    "replicas": 2,
    "cpu_request": "250m",
    "cpu_limit": "500m",
    "memory_request": "256Mi",
    "memory_limit": "512Mi",
    "container_port": 80,
    "expose_external": true,
    "namespace": "demo-api-staging",
    "deployment_name": "demo-api-deployment",
    "service_name_k8s": "demo-api-service",
    "ingress_name": "demo-api-ingress",
    "ingress_host": "demo-api.staging.local",
    "status": "RUNNING",
    "last_error_code": null,
    "last_error_message": null,
    "created_at": "2026-07-03T12:00:00+09:00",
    "updated_at": "2026-07-03T12:01:30+09:00"
  },
  "message": "success"
}
```

## 7. Pod 상태 조회

### `GET /projects/{project_id}/pods`

프로젝트 Namespace의 Pod 상태를 조회한다.

### Response `200 OK`

```json
{
  "data": {
    "project_id": 1,
    "namespace": "demo-api-staging",
    "pods": [
      {
        "name": "demo-api-deployment-7c9d7f8c7d-xk2la",
        "phase": "Running",
        "ready": true,
        "restart_count": 0,
        "node_name": "portal-dev-control-plane",
        "pod_ip": "10.244.0.12",
        "containers": [
          {
            "name": "demo-api",
            "image": "nginx:latest",
            "ready": true,
            "state": "running",
            "waiting_reason": null,
            "terminated_reason": null
          }
        ],
        "created_at": "2026-07-03T12:00:15+09:00"
      }
    ]
  },
  "message": "success"
}
```

### 실패 상태 예시

```json
{
  "data": {
    "project_id": 2,
    "namespace": "broken-api-staging",
    "pods": [
      {
        "name": "broken-api-deployment-77d8c7d8b8-abcd1",
        "phase": "Pending",
        "ready": false,
        "restart_count": 0,
        "containers": [
          {
            "name": "broken-api",
            "image": "nginx-not-exist:latest",
            "ready": false,
            "state": "waiting",
            "waiting_reason": "ImagePullBackOff",
            "terminated_reason": null
          }
        ]
      }
    ]
  },
  "message": "success"
}
```

## 8. Kubernetes Event 조회

### `GET /projects/{project_id}/events`

프로젝트 Namespace의 최근 Kubernetes Event를 조회한다.

### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| limit | integer | N | 기본값 20 |

### Response `200 OK`

```json
{
  "data": {
    "project_id": 1,
    "namespace": "demo-api-staging",
    "events": [
      {
        "type": "Warning",
        "reason": "Failed",
        "message": "Failed to pull image \"nginx-not-exist:latest\"",
        "involved_object_kind": "Pod",
        "involved_object_name": "broken-api-deployment-77d8c7d8b8-abcd1",
        "count": 3,
        "first_timestamp": "2026-07-03T12:02:00+09:00",
        "last_timestamp": "2026-07-03T12:03:30+09:00"
      }
    ]
  },
  "message": "success"
}
```

## 9. 프로젝트 상태 동기화

### `POST /projects/{project_id}/sync-status`

Kubernetes 상태를 조회해 DB의 프로젝트 상태를 갱신한다.

### Response `200 OK`

```json
{
  "data": {
    "project_id": 1,
    "previous_status": "PROVISIONING",
    "current_status": "RUNNING",
    "reason": "all pods are ready"
  },
  "message": "status synchronized"
}
```

### 상태 판단 기준

| 조건 | 상태 |
|---|---|
| 모든 Pod Ready | RUNNING |
| ImagePullBackOff | FAILED |
| CrashLoopBackOff | FAILED |
| Pod Pending 지속 | PROVISIONING 또는 FAILED |
| Deployment 없음 | FAILED |

## 10. 프로젝트 삭제

### `DELETE /projects/{project_id}`

프로젝트와 관련된 Kubernetes 리소스를 삭제한다.

### Response `200 OK`

```json
{
  "data": {
    "project_id": 1,
    "namespace": "demo-api-staging",
    "status": "DELETED",
    "deleted_resources": [
      "ingress/demo-api-ingress",
      "service/demo-api-service",
      "deployment/demo-api-deployment",
      "resourcequota/demo-api-quota",
      "namespace/demo-api-staging"
    ]
  },
  "message": "project deleted"
}
```

### Error Cases

| 코드 | 조건 | 설명 |
|---|---|---|
| PROJECT_NOT_FOUND | project_id 없음 | 삭제 대상 없음 |
| PROJECT_ALREADY_DELETED | 이미 삭제됨 | 상태 충돌 |
| K8S_DELETE_FAILED | Kubernetes 삭제 실패 | 일부 리소스 삭제 실패 |

## 11. Audit Log 조회

### `GET /audit-logs`

생성/삭제/상태 변경 로그를 조회한다.

### Query Parameters

| 파라미터 | 타입 | 필수 | 설명 |
|---|---|---|---|
| project_id | integer | N | 프로젝트 ID 필터 |
| action | string | N | CREATE, DELETE, STATUS_CHANGE 등 |
| page | integer | N | 기본값 1 |
| size | integer | N | 기본값 20 |

### Response `200 OK`

```json
{
  "data": {
    "items": [
      {
        "id": 1,
        "project_id": 1,
        "action": "CREATE_PROJECT",
        "target_type": "PROJECT",
        "target_name": "demo-api-staging",
        "result": "SUCCESS",
        "message": "project request created",
        "created_at": "2026-07-03T12:00:00+09:00"
      }
    ],
    "page": 1,
    "size": 20,
    "total": 1
  },
  "message": "success"
}
```

## 12. Health Check

### `GET /health`

백엔드 상태를 확인한다.

### Response

```json
{
  "status": "UP",
  "database": "UP",
  "kubernetes": "UP"
}
```

## 13. API 우선 구현 순서

1. `GET /health`
2. `POST /projects`
3. `GET /projects`
4. `GET /projects/{project_id}`
5. `GET /projects/{project_id}/pods`
6. `GET /projects/{project_id}/events`
7. `DELETE /projects/{project_id}`
8. `GET /audit-logs`
