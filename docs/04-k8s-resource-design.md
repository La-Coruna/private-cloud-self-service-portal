# 04. Kubernetes 리소스 설계 문서

## 1. 문서 목적

이 문서는 Self-Service Portal이 생성·조회·삭제할 Kubernetes 리소스의 이름 규칙, Label/Annotation 규칙, 리소스별 생성 정책, 삭제 정책을 정의한다.

## 2. 설계 원칙

1. 모든 리소스는 플랫폼이 추적할 수 있는 Label을 가진다.
2. 사용자가 직접 Kubernetes YAML을 작성하지 않아도 표준 리소스가 생성되어야 한다.
3. Namespace 단위로 리소스를 격리한다.
4. ResourceQuota로 자원 사용량을 제한한다.
5. 삭제 시 플랫폼이 생성한 리소스만 정리한다.
6. 리소스 이름은 예측 가능하고 중복 가능성이 낮아야 한다.

## 3. 리소스 생성 대상

MVP에서 생성하는 리소스는 다음과 같다.

| 리소스 | 생성 조건 | 목적 |
|---|---|---|
| Namespace | 항상 생성 | 프로젝트/환경 단위 격리 |
| ResourceQuota | MVP 2부터 생성 | Namespace 자원 사용량 제한 |
| Deployment | 항상 생성 | 애플리케이션 Pod 관리 |
| Service | 항상 생성 | Pod 내부 접근 엔드포인트 제공 |
| Ingress | expose_external=true일 때 생성 | 외부 HTTP 접근 제공 |

## 4. Naming Convention

### 4.1 기본 규칙

- 소문자 영문, 숫자, 하이픈만 사용한다.
- 공백과 특수문자는 하이픈으로 변환한다.
- 이름 길이는 Kubernetes DNS label 제약을 고려해 제한한다.
- 동일 서비스명/환경 중복은 DB와 Kubernetes 조회로 방지한다.

### 4.2 Namespace 이름

형식:

```text
{service-name}-{environment}
```

예시:

```text
demo-api-staging
order-api-dev
movie-recommender-prod
```

### 4.3 Deployment 이름

형식:

```text
{service-name}-deployment
```

예시:

```text
demo-api-deployment
```

### 4.4 Service 이름

형식:

```text
{service-name}-service
```

예시:

```text
demo-api-service
```

### 4.5 Ingress 이름

형식:

```text
{service-name}-ingress
```

예시:

```text
demo-api-ingress
```

### 4.6 ResourceQuota 이름

형식:

```text
{service-name}-quota
```

예시:

```text
demo-api-quota
```

## 5. Label 규칙

모든 리소스에는 다음 공통 Label을 부여한다.

```yaml
app.kubernetes.io/managed-by: self-service-portal
app.kubernetes.io/name: demo-api
app.kubernetes.io/instance: demo-api-staging
platform.local/project-id: "1"
platform.local/environment: staging
platform.local/resource-owner: portal
```

### Label 목적

| Label | 목적 |
|---|---|
| app.kubernetes.io/managed-by | 포털이 생성한 리소스 식별 |
| app.kubernetes.io/name | 서비스명 식별 |
| app.kubernetes.io/instance | 서비스명+환경 단위 인스턴스 식별 |
| platform.local/project-id | DB 프로젝트 ID와 연결 |
| platform.local/environment | dev/staging/prod 환경 구분 |
| platform.local/resource-owner | 플랫폼 관리 대상 식별 |

## 6. Annotation 규칙

필요 시 다음 Annotation을 사용한다.

```yaml
platform.local/created-by: self-service-portal
platform.local/requested-at: "2026-07-03T12:00:00+09:00"
platform.local/source: api
platform.local/description: "created by private cloud self-service portal"
```

Annotation은 검색 조건보다는 상세 메타데이터 기록에 사용한다.

## 7. Namespace 설계

### 7.1 생성 예시

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: demo-api-staging
  labels:
    app.kubernetes.io/managed-by: self-service-portal
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/instance: demo-api-staging
    platform.local/project-id: "1"
    platform.local/environment: staging
    platform.local/resource-owner: portal
```

### 7.2 정책

- 하나의 프로젝트 신청은 하나의 Namespace를 가진다.
- Namespace는 `{service-name}-{environment}`로 생성한다.
- 동일 Namespace가 이미 있으면 생성 실패로 처리한다.
- 삭제 시 Namespace 삭제를 통해 하위 리소스 전체 정리를 보장한다.

## 8. ResourceQuota 설계

### 8.1 기본 Quota

MVP 기본값:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: demo-api-quota
  namespace: demo-api-staging
spec:
  hard:
    requests.cpu: "1"
    requests.memory: 1Gi
    limits.cpu: "2"
    limits.memory: 2Gi
    pods: "5"
```

### 8.2 정책

- ResourceQuota는 Namespace 생성 직후 생성한다.
- 사용자가 입력한 Deployment 리소스 값은 Quota 범위 내에 있어야 한다.
- Quota 생성 실패 시 프로젝트 상태를 `FAILED`로 변경한다.

## 9. Deployment 설계

### 9.1 생성 예시

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo-api-deployment
  namespace: demo-api-staging
  labels:
    app.kubernetes.io/managed-by: self-service-portal
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/instance: demo-api-staging
    platform.local/project-id: "1"
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: demo-api
      app.kubernetes.io/instance: demo-api-staging
  template:
    metadata:
      labels:
        app.kubernetes.io/name: demo-api
        app.kubernetes.io/instance: demo-api-staging
        app.kubernetes.io/managed-by: self-service-portal
        platform.local/project-id: "1"
    spec:
      containers:
        - name: demo-api
          image: nginx:latest
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
```

### 9.2 정책

- MVP에서는 컨테이너 포트를 기본값 80으로 둔다.
- replicas 기본값은 1, 입력 가능 범위는 1~5로 제한한다.
- image는 문자열 검증만 수행하고 실제 존재 여부는 Kubernetes Event를 통해 확인한다.
- Deployment Selector는 `app.kubernetes.io/name`, `app.kubernetes.io/instance`를 사용한다.

## 10. Service 설계

### 10.1 생성 예시

```yaml
apiVersion: v1
kind: Service
metadata:
  name: demo-api-service
  namespace: demo-api-staging
  labels:
    app.kubernetes.io/managed-by: self-service-portal
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/instance: demo-api-staging
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/instance: demo-api-staging
  ports:
    - name: http
      port: 80
      targetPort: 80
```

### 10.2 정책

- Service type은 MVP에서 ClusterIP로 고정한다.
- 외부 공개는 Service type LoadBalancer가 아니라 Ingress로 처리한다.
- Service selector는 Deployment Pod label과 반드시 일치해야 한다.

## 11. Ingress 설계

### 11.1 생성 조건

`expose_external = true`일 때만 생성한다.

### 11.2 Host 규칙

형식:

```text
{service-name}.{environment}.local
```

예시:

```text
demo-api.staging.local
```

### 11.3 생성 예시

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: demo-api-ingress
  namespace: demo-api-staging
  labels:
    app.kubernetes.io/managed-by: self-service-portal
    app.kubernetes.io/name: demo-api
    app.kubernetes.io/instance: demo-api-staging
spec:
  ingressClassName: nginx
  rules:
    - host: demo-api.staging.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: demo-api-service
                port:
                  number: 80
```

### 11.4 정책

- 로컬 kind에서는 NGINX Ingress Controller 설치 후 테스트한다.
- Ingress Controller가 설치되지 않은 경우 Ingress 생성은 성공해도 외부 접근은 실패할 수 있으므로 Event/문서로 안내한다.
- MVP에서는 TLS를 제외한다.

## 12. 삭제 정책

삭제 순서:

```text
1. Ingress 삭제
2. Service 삭제
3. Deployment 삭제
4. ResourceQuota 삭제
5. Namespace 삭제
6. DB 상태 업데이트
7. Audit Log 저장
```

원칙:

- 플랫폼 Label이 붙은 리소스만 삭제한다.
- Namespace 삭제 전 개별 리소스 삭제를 먼저 시도한다.
- 일부 리소스 삭제 실패 시 Audit Log에 실패 원인을 기록한다.
- Namespace 삭제가 성공하면 하위 리소스는 Kubernetes garbage collection에 의해 정리된다.

## 13. 상태 조회 대상

### 13.1 Pod 조회

조회 조건:

```text
namespace = project.namespace
labelSelector = app.kubernetes.io/instance={service-name}-{environment}
```

응답 필드:

- Pod name
- phase
- ready
- restart count
- container state
- waiting reason
- image
- node name
- started at

### 13.2 Event 조회

조회 조건:

```text
namespace = project.namespace
sort by lastTimestamp desc
limit = 20
```

응답 필드:

- type
- reason
- message
- involved object kind/name
- count
- first timestamp
- last timestamp

## 14. 예상 실패 케이스

| 케이스 | Kubernetes 상태 | 포털 표시 |
|---|---|---|
| 이미지 없음 | ImagePullBackOff | 이미지 Pull 실패 |
| Quota 초과 | FailedCreate / Forbidden | Namespace ResourceQuota 초과 |
| CPU/Memory 형식 오류 | API validation error | 리소스 요청값 형식 오류 |
| Ingress Controller 없음 | 외부 접근 실패 | Ingress Controller 미설치 가능성 안내 |
| Namespace 중복 | AlreadyExists | 동일 서비스/환경이 이미 존재 |
| RBAC 권한 부족 | Forbidden | 플랫폼 백엔드 권한 부족 |

## 15. 확장 고려

- LimitRange 추가
- NetworkPolicy 추가
- ServiceAccount per namespace 생성
- ConfigMap/Secret 신청 기능
- HPA 설정 기능
- Helm Chart 템플릿화
- ArgoCD Application 생성
