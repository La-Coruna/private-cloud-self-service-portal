# Firebase Hosting + Cloud Run + Firestore 전환 설계

## 1. 배경과 목표

현재 포털의 React 프런트엔드, FastAPI 백엔드, MariaDB, 사용자 프로젝트 워크로드는 하나의 GKE Standard Spot 노드 풀에 함께 배치되어 있다. Spot 노드가 교체되면 사용자 워크로드뿐 아니라 포털과 데이터베이스도 동시에 중단된다. 2026-08-12 장애에서는 MariaDB 복구가 늦어 FastAPI 시작이 실패했고, DB 연결 재시도를 추가해 자동 복구는 가능해졌지만 포털 자체가 Spot 노드 수명주기에 종속된 근본 문제는 남아 있다.

이번 전환의 목표는 포털 제어 영역을 GKE Spot 노드에서 분리하는 것이다.

- React 정적 프런트엔드는 Firebase Hosting에서 제공한다.
- FastAPI 백엔드는 Cloud Run에서 실행한다.
- 프로젝트와 감사 로그는 Cloud Firestore에 저장한다.
- GKE Spot 노드에는 사용자가 생성한 프로젝트 워크로드와 이를 노출하는 공유 ingress-nginx만 유지한다.
- Spot 노드 교체 중에도 포털 접속, 저장된 프로젝트 조회, 감사 로그 조회가 가능해야 한다.
- 남은 무료 크레딧 기간 동안 안정성을 우선하되 불필요한 상시 비용은 만들지 않는다.

## 2. 확정된 범위

### 포함

- 기존 React SPA를 Firebase Hosting으로 이전
- 기존 FastAPI API를 Cloud Run으로 이전
- MariaDB/SQLAlchemy 저장소를 Firestore 저장소로 교체
- Cloud Run 전용 IAM 서비스 계정과 최소 권한 구성
- GKE DNS 기반 제어 평면 endpoint와 IAM 인증 사용
- IAM 서비스 계정에 Kubernetes RBAC 부여
- 기존 프로젝트 상태 6종 유지
- 플랫폼 가용성 상태 3종 추가
- GKE 복구 안내 배너, 생성 차단, 실시간 상태 unavailable 처리
- 읽기 요청의 제한된 자동 재시도
- Firebase 기본 도메인에서 사전 검증 후 기존 사용자 도메인 전환
- 24시간 병행 운영과 단계별 롤백
- 기존 데모 프로젝트와 MariaDB 데이터 정리 후 Firestore에서 빈 상태로 시작
- 전환 작업 로그와 공개용 블로그 초안 동시 작성

### 제외

- 기존 MariaDB 데이터 마이그레이션
- Firebase Authentication 또는 사용자별 권한
- Pub/Sub 또는 Cloud Tasks 기반 비동기 프로비저닝
- 다중 GKE 클러스터 지원
- 사용자 워크로드의 Spot 중단 자체를 제거하는 작업
- 기존 포털 제거 전 자동 DNS 롤백

## 3. 목표 아키텍처

```text
사용자 브라우저
  -> portal.la-coruna.xyz
  -> Firebase Hosting
       -> React SPA 정적 파일
       -> /api/**, /health rewrite
          -> Cloud Run FastAPI (asia-northeast3)
               -> Firestore (asia-northeast3)
               -> GKE DNS endpoint
                    -> GKE Kubernetes API
                    -> Spot 노드의 사용자 프로젝트 워크로드
```

Firebase Hosting은 정적 파일, CDN, TLS, SPA fallback을 담당한다. `/api/**`와 `/health`는 같은 도메인에서 Cloud Run으로 rewrite한다. 따라서 브라우저는 별도 API 도메인이나 운영 CORS 설정에 의존하지 않는다.

Cloud Run은 `asia-northeast3`에서 실행하며 최소 인스턴스 0, 최대 인스턴스 2로 시작한다. 전용 사용자 관리 서비스 계정을 서비스 identity로 사용하고 키 파일은 만들지 않는다. Firestore도 비용과 지연을 고려해 서울 지역형 데이터베이스로 생성한다. Firestore 위치는 생성 후 변경할 수 없으므로 배포 전에 `asia-northeast3`를 확인한다.

## 4. 인증과 권한 경계

Cloud Run은 Application Default Credentials로 Firestore와 GKE에 접근한다.

- Cloud Run 전용 IAM 서비스 계정에 Firestore 데이터 접근 역할을 부여한다.
- GKE DNS endpoint 접근에 필요한 IAM 권한을 부여한다.
- Kubernetes에서는 해당 IAM 서비스 계정 이메일을 `User` subject로 사용해 현재 포털 수준의 RBAC를 부여한다.
- RBAC는 Namespace, ResourceQuota, Deployment, Service, Ingress, Pod, Event의 필요한 get/list/watch/create/delete 동작만 허용한다.
- RBAC 또는 IAM 리소스를 수정할 권한은 Cloud Run에 부여하지 않는다.
- GKE DNS endpoint가 검증되기 전에는 기존 IP endpoint를 유지한다. 이후 IP endpoint 축소는 별도의 안전성 검토 대상으로 남긴다.

포털과 Cloud Run API는 로그인 없는 공개 데모로 유지한다. 대신 서버에서 다음 제한을 강제한다.

- 활성 프로젝트 최대 3개
- 프로젝트별 replica 최대 1개
- 기존 이미지 허용 목록 유지
- 서비스 이름 prefix 제한 유지
- Cloud Run 최대 인스턴스 2

## 5. 상태 모델

### 5.1 프로젝트 생명주기

기존의 다음 6개 상태를 그대로 유지한다.

- `REQUESTED`
- `PROVISIONING`
- `RUNNING`
- `FAILED`
- `DELETING`
- `DELETED`

정상 전이는 다음과 같다.

```text
REQUESTED -> PROVISIONING -> RUNNING
                       \-> FAILED

RUNNING 또는 FAILED -> DELETING -> DELETED
```

Spot 노드 교체만으로 저장된 프로젝트 상태를 즉시 `FAILED`로 바꾸지 않는다. 프로젝트 상태는 배포 생명주기를, 플랫폼 상태는 현재 GKE 가용성을 표현한다. 사용자가 명시적으로 상태 동기화를 수행했을 때 실제 Pod/Event가 배포 실패를 나타내면 기존 규칙에 따라 `FAILED`로 전환할 수 있다.

### 5.2 플랫폼 가용성

- `AVAILABLE`: Kubernetes API 연결 가능, 스케줄 가능한 Ready 노드가 1대 이상
- `RECOVERING`: Kubernetes API 연결 가능, 스케줄 가능한 Ready 노드가 없음
- `UNAVAILABLE`: Kubernetes API 인증, 네트워크 또는 API 연결 실패

플랫폼 상태는 프로젝트 문서에 저장하지 않고 요청 시 GKE에서 판정한다. 프런트엔드는 `/api/platform-status`를 15초마다 조회한다.

## 6. Firestore 데이터 모델

### 6.1 프로젝트

경로: `projects/{namespace}`

문서 ID는 Kubernetes Namespace와 같은 문자열을 사용한다. 기존 숫자형 ID는 유지하지 않는다.

주요 필드:

- `id`, `namespace`
- `service_name`, `environment`, `image`, `replicas`
- `cpu_request`, `cpu_limit`, `memory_request`, `memory_limit`
- `expose_external`, `ingress_host`
- `status`, `error_message`
- `capacity_claimed`
- `created_at`, `updated_at`

문서 ID를 Namespace로 고정해 같은 Namespace의 중복 요청을 방지한다.

### 6.2 감사 로그

경로: `projects/{namespace}/auditLogs/{logId}`

주요 필드:

- `id`, `project_id`
- `action`, `status`, `message`
- `created_at`

`project_id`는 Namespace 문자열이다. 감사 로그는 `created_at`, `id` 순으로 정렬한다.

### 6.3 데모 용량

경로: `system/demoCapacity`

주요 필드:

- `active_count`
- `max_active_projects`
- `updated_at`

프로젝트 생성 시 Firestore 트랜잭션에서 프로젝트 중복 여부와 활성 슬롯을 함께 검사하고 `capacity_claimed=true`로 저장한다. 생성 실패 또는 삭제 완료 시 `capacity_claimed`가 true일 때만 슬롯을 반환하고 false로 갱신해 중복 반환을 막는다.

활성 슬롯은 `REQUESTED`, `PROVISIONING`, `RUNNING` 프로젝트가 점유한다. Kubernetes 생성 실패로 `FAILED`가 되면 즉시 슬롯을 반환한다. 삭제 실패로 `FAILED`가 된 경우에는 Kubernetes 리소스가 남아 있을 수 있으므로 슬롯을 유지한다. 이를 구분하기 위해 슬롯 반환 여부는 상태가 아니라 `capacity_claimed`로 판단한다.

## 7. API와 요청 흐름

기존 API 경로를 최대한 유지하되 `{project_id}`는 Namespace 문자열로 바꾼다.

- `GET /api/projects`
- `POST /api/projects`
- `GET /api/projects/{namespace}`
- `GET /api/projects/{namespace}/pods`
- `GET /api/projects/{namespace}/events`
- `GET /api/projects/{namespace}/audit-logs`
- `POST /api/projects/{namespace}/sync-status`
- `DELETE /api/projects/{namespace}`
- `GET /api/platform-status`
- `GET /health`

### 프로젝트 생성

1. 입력값과 공개 데모 제한을 검증한다.
2. 플랫폼 상태가 `AVAILABLE`인지 확인한다.
3. Firestore 트랜잭션으로 중복과 최대 3개 제한을 확인하고 `REQUESTED` 프로젝트와 슬롯을 생성한다.
4. 상태를 `PROVISIONING`으로 갱신하고 감사 로그를 기록한다.
5. Namespace, ResourceQuota, Deployment, Service, 선택적 Ingress를 순서대로 생성한다.
6. 성공하면 `RUNNING`, 실패하면 `FAILED`와 원인을 저장한다.
7. 생성 실패 시 점유한 슬롯을 정확히 한 번 반환한다.

기존 Kubernetes 클라이언트의 `already_exists` 처리를 유지해 부분 생성 이후 재시도에 안전하도록 한다. POST 생성 요청은 브라우저가 자동 재시도하지 않는다.

### 조회와 상태 동기화

Firestore 기반 목록, 상세, 감사 로그는 GKE 장애와 무관하게 제공한다. Pod와 Event는 실시간 GKE 조회이며 GKE 연결 실패 시 표준 오류 코드 `GKE_UNAVAILABLE`을 반환한다. 상태 동기화는 프로젝트 상태와 실제 Pod/Event를 비교해 기존 상태 판정 규칙을 적용한다.

### 삭제

삭제는 `DELETING`으로 전환한 뒤 Ingress, Service, Deployment, ResourceQuota, Namespace 역순으로 수행한다. 모든 대상이 삭제 또는 이미 없음이면 `DELETED`로 바꾸고 슬롯을 반환한다. GKE 연결이 불가능하면 삭제를 시작하지 않는다. 일부 삭제 후 실패하면 `FAILED`와 상세 감사 로그를 남기고 슬롯은 유지한다.

## 8. 장애 처리와 사용자 경험

`GET /health`는 Cloud Run 애플리케이션과 Firestore가 정상이라면 HTTP 200을 반환한다. GKE 장애만으로 Cloud Run revision을 비정상으로 만들지 않는다. 응답에는 Firestore와 GKE 상태를 각각 포함한다.

프런트엔드는 플랫폼 상태에 따라 다음과 같이 동작한다.

- `AVAILABLE`: 모든 기능 활성화
- `RECOVERING`: “GKE 워크로드 복구 중” 배너 표시, 생성 차단, 저장 정보와 감사 로그 제공, Pod/Event unavailable 표시, 기존 프로젝트 삭제와 상태 조회는 시도 가능
- `UNAVAILABLE`: 배너 표시, 생성·삭제·동기화 차단, 저장 정보와 감사 로그 제공, Pod/Event unavailable 표시

`RECOVERING`에서 삭제를 허용하는 이유는 제어 평면이 정상이고 API 요청을 처리할 수 있기 때문이다. 각 작업 직전에 서버가 상태를 다시 확인하므로 프런트 상태가 오래되어도 안전하게 차단된다.

GET 요청은 제한된 지수 백오프로 재시도한다. 생성, 삭제, 상태 동기화 같은 변경 요청은 자동 재시도하지 않는다. 플랫폼 상태가 회복되면 다음 폴링에서 배너와 생성 제한이 자동 해제된다.

## 9. 배포와 롤백

### 단계적 전환

1. 코드와 자동화 테스트를 완성한다.
2. 기존 데모 프로젝트 Namespace를 정리하되 기존 포털은 유지한다.
3. Firestore, Cloud Run 전용 서비스 계정과 IAM을 준비한다.
4. GKE DNS endpoint를 활성화한다.
5. Cloud Run 기본 주소에서 Firestore와 GKE 접근을 검증한다.
6. Firebase 기본 `web.app` 주소에서 SPA, API rewrite, 전체 기능을 검증한다.
7. DNS TTL을 낮추고 기존 Load Balancer 주소를 기록한다.
8. `portal.la-coruna.xyz`를 Firebase Hosting에 연결한다.
9. 외부 도메인에서 생성, 조회, 동기화, 삭제와 장애 안내를 검증한다.
10. 최소 24시간 신규 구조와 기존 GKE 포털을 병행 운영한다.
11. 별도 승인 후 GKE의 포털 React, FastAPI, MariaDB, 포털 Ingress를 제거한다.
12. 사용자 워크로드용 Spot 노드와 공유 ingress-nginx는 유지한다.

### 롤백

- 도메인 전환 전 실패: 신규 Firebase/Cloud Run 작업을 중단한다. 기존 서비스는 영향받지 않는다.
- 도메인 전환 후 실패: DNS를 기록해 둔 기존 GKE Load Balancer로 되돌린다.
- 기존 포털 제거 후 실패: Git에 보존된 Kubernetes 매니페스트와 Artifact Registry 이미지를 사용해 기존 포털을 재배포한다.
- MariaDB PVC는 24시간 관찰과 별도 승인 전까지 제거하지 않는다.

DNS 캐시로 신규와 기존 주소가 잠시 혼재할 수 있으므로 TTL을 사전에 낮춘다. 신규 구조가 검증되기 전에는 기존 포털 리소스를 삭제하지 않는다.

## 10. 테스트와 완료 기준

### 자동화 테스트

- Firestore Repository의 생성, 조회, 수정, 정렬, 중복 처리
- Firestore 트랜잭션 기반 최대 3개 제한과 슬롯 반환
- 6단계 프로젝트 상태 전이
- 3단계 플랫폼 상태 판정
- GKE 불가 시 API별 허용·차단 규칙
- 기존 Kubernetes 리소스 생성·삭제·상태 판정 회귀 테스트
- 프런트 장애 배너와 생성 버튼 비활성화
- GET 재시도 및 변경 요청 비재시도
- 문자열 프로젝트 ID 라우팅
- Firebase SPA fallback과 API rewrite 구성 검증

### 운영 검증

- Cloud Run 기본 URL의 `/health`
- Cloud Run 서비스 identity의 Firestore 접근
- Cloud Run 서비스 identity의 GKE DNS endpoint/RBAC 접근
- Firebase 기본 도메인의 프로젝트 생성, 조회, Pod/Event, 동기화, 삭제
- 동시 생성 요청에도 활성 프로젝트 3개 제한
- Spot 노드 교체 중 포털 접속과 Firestore 조회 유지
- `RECOVERING` 배너, 생성 차단, GKE 회복 후 자동 해제
- 사용자 도메인의 HTTPS, SPA 직접 경로, `/api/**`, `/health`
- 전환 후 Cloud Logging 오류와 예상 비용 항목 확인

완료 조건은 신규 사용자 도메인에서 전체 기능과 장애 시나리오가 통과하고, 24시간 관찰 중 치명적 오류가 없으며, 기존 GKE 포털 제거에 사용자가 별도로 승인하는 것이다.

## 11. 작업 기록과 블로그 초안

구현과 배포 과정에서 다음 문서를 지속적으로 갱신한다.

- `docs/migration/firebase-cloud-run-firestore-migration-log.md`: 시간순 작업 원본, 명령, 결과, 오류, 해결, 검증, 롤백 판단
- `docs/migration/firebase-cloud-run-firestore-blog-draft.md`: 공개 가능한 서술형 블로그 초안

블로그 초안은 장애 배경, DB 재시도 임시 조치, 기존 구조의 한계, 목표 아키텍처, Firestore 전환, Cloud Run의 GKE 접근, IAM/RBAC, 상태 모델 분리, 단계적 DNS 전환, Spot 장애 검증, 비용 변화, 회고 순으로 구성한다.

작업 기록에는 스크린샷 후보와 촬영 시점도 남긴다. 프로젝트 번호, 토큰, 자격 증명, 내부 인증 정보, 비밀번호는 기록하지 않거나 공개 문서에서 마스킹한다.

## 12. 구현 영향 범위

- 낮음: 프로젝트 상태 enum, 입력 스키마, Kubernetes 리소스 모델과 생성·삭제 순서
- 중간: 프런트 API 타입, 문자열 라우팅, 플랫폼 배너, 요청 재시도
- 중간~높음: Kubernetes 인증 초기화, Cloud Run 실행 설정, health 의미
- 높음: SQLAlchemy/MariaDB 저장소와 결합된 Router 및 테스트를 Firestore Repository 구조로 교체
- 높음: Firebase Hosting, Cloud Run, Firestore, IAM, GKE DNS endpoint 배포 자동화

기존 React 화면과 Kubernetes 리소스 조작 코드는 가능한 한 재사용한다. 저장소 인터페이스를 Router에서 분리해 Firestore 세부 구현이 API와 프로비저닝 로직에 다시 결합되지 않도록 한다.
