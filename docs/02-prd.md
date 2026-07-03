# 02. 요구사항 정의서 PRD

## 1. 문서 목적

이 문서는 Kubernetes 기반 Private Cloud Self-Service Portal의 사용자 시나리오, 기능 요구사항, 비기능 요구사항, MVP 범위, 성공 기준을 정의한다.

## 2. 제품 개요

본 제품은 개발자가 Kubernetes 리소스를 직접 작성하지 않고 웹 화면 또는 API를 통해 서비스 배포를 신청할 수 있게 하는 내부 클라우드 포털이다. 플랫폼은 사용자의 입력값을 검증한 뒤 조직 표준에 맞는 Kubernetes 리소스를 생성하고, 배포 상태와 실패 원인을 조회할 수 있게 한다.

## 3. 사용자 페르소나

### 3.1 서비스 개발자

- 목표: 개발 중인 서비스를 staging/dev 환경에 빠르게 배포하고 싶다.
- 어려움: YAML, kubectl, Ingress, ResourceQuota, Pod Event 분석에 익숙하지 않다.
- 기대: 웹에서 최소 정보만 입력하면 배포되고, 실패 원인도 한눈에 보고 싶다.

### 3.2 플랫폼 운영자

- 목표: 개발자들이 표준화된 방식으로 Kubernetes 리소스를 생성하게 하고 싶다.
- 어려움: 개발자가 직접 만든 리소스의 이름, Label, Quota, Ingress 규칙이 제각각이다.
- 기대: 모든 리소스가 관리 규칙을 따르고, 생성/삭제 이력이 남아야 한다.

## 4. 핵심 사용자 시나리오

### 시나리오 1. 서비스 배포 신청

1. 개발자가 포털에 접속한다.
2. 프로젝트 생성 화면에서 다음 정보를 입력한다.
   - 서비스명: `demo-api`
   - 환경: `staging`
   - 이미지: `nginx:latest`
   - Replicas: `2`
   - CPU request: `250m`
   - CPU limit: `500m`
   - Memory request: `256Mi`
   - Memory limit: `512Mi`
   - 외부 공개 여부: `true`
3. 포털은 입력값을 검증한다.
4. 포털은 신청 정보를 DB에 저장한다.
5. 포털은 Kubernetes에 Namespace, ResourceQuota, Deployment, Service, Ingress를 생성한다.
6. 사용자는 프로젝트 상세 화면에서 배포 상태를 확인한다.

### 시나리오 2. 배포 상태 확인

1. 개발자가 프로젝트 상세 화면에 접속한다.
2. 포털은 Kubernetes API에서 Deployment, Pod, Event 정보를 조회한다.
3. 사용자는 Pod phase, Ready 상태, Restart count, Event message를 확인한다.

### 시나리오 3. 배포 실패 확인

1. 개발자가 존재하지 않는 이미지명을 입력해 배포한다.
2. Pod가 `ImagePullBackOff` 상태가 된다.
3. 포털은 Pod container state와 Event를 조회한다.
4. 사용자는 웹 화면에서 실패 원인을 확인한다.

### 시나리오 4. 리소스 삭제

1. 개발자가 프로젝트 삭제 버튼을 누른다.
2. 포털은 Ingress, Service, Deployment, ResourceQuota, Namespace 순서로 리소스를 삭제한다.
3. 포털은 DB 상태를 `DELETED`로 변경한다.
4. Audit Log에 삭제 이력이 남는다.

## 5. 기능 요구사항

### FR-001. 프로젝트 생성

- 사용자는 서비스 배포 정보를 입력해 프로젝트를 생성할 수 있어야 한다.
- 시스템은 서비스명, 환경, 이미지명, 리소스 제한값, 외부 공개 여부를 입력받아야 한다.
- 시스템은 입력값을 검증해야 한다.
- 시스템은 신청 정보를 DB에 저장해야 한다.

### FR-002. Kubernetes Namespace 생성

- 시스템은 프로젝트 생성 시 서비스명과 환경을 기반으로 Namespace를 생성해야 한다.
- Namespace에는 플랫폼 관리용 Label이 포함되어야 한다.
- 이미 존재하는 Namespace일 경우 중복 생성 오류를 처리해야 한다.

### FR-003. ResourceQuota 생성

- 시스템은 Namespace 단위 ResourceQuota를 생성할 수 있어야 한다.
- 기본 Quota는 플랫폼 기본값을 사용한다.
- Quota 생성 실패 시 프로젝트 상태를 `FAILED`로 변경해야 한다.

### FR-004. Deployment 생성

- 시스템은 사용자가 입력한 이미지, replicas, CPU/Memory 값을 기반으로 Deployment를 생성해야 한다.
- Deployment에는 표준 Label과 Selector가 적용되어야 한다.
- 컨테이너 포트는 MVP에서 기본값 `80`으로 둔다.

### FR-005. Service 생성

- 시스템은 Deployment 앞에 ClusterIP Service를 생성해야 한다.
- Service는 Deployment Pod를 Label Selector로 연결해야 한다.

### FR-006. Ingress 생성

- 외부 공개 여부가 true이면 Ingress를 생성해야 한다.
- 외부 공개 여부가 false이면 Ingress를 생성하지 않는다.
- Ingress host는 `{service-name}.{environment}.local` 형식을 사용한다.

### FR-007. 프로젝트 목록 조회

- 사용자는 생성된 프로젝트 목록을 조회할 수 있어야 한다.
- 목록에는 서비스명, 환경, 이미지, 상태, Namespace, 생성일이 표시되어야 한다.

### FR-008. 프로젝트 상세 조회

- 사용자는 프로젝트 상세 정보를 조회할 수 있어야 한다.
- 상세 정보에는 신청 정보, Kubernetes 리소스 이름, 현재 상태가 포함되어야 한다.

### FR-009. Pod 상태 조회

- 사용자는 프로젝트의 Pod 목록과 상태를 조회할 수 있어야 한다.
- 조회 정보에는 Pod name, phase, ready, restart count, container state, waiting reason이 포함되어야 한다.

### FR-010. Kubernetes Event 조회

- 사용자는 프로젝트 Namespace에서 발생한 최근 Event를 조회할 수 있어야 한다.
- Event에는 type, reason, message, involved object, timestamp가 포함되어야 한다.

### FR-011. 프로젝트 삭제

- 사용자는 생성한 프로젝트를 삭제할 수 있어야 한다.
- 시스템은 플랫폼이 생성한 리소스만 삭제해야 한다.
- 삭제 결과는 DB 상태와 Audit Log에 반영되어야 한다.

### FR-012. Audit Log 저장

- 시스템은 생성, 상태 변경, 삭제, 실패 이벤트를 Audit Log로 저장해야 한다.
- Audit Log에는 action, target, result, message, created_at이 포함되어야 한다.

## 6. 비기능 요구사항

### NFR-001. 재현성

- README만 보고 로컬에서 실행할 수 있어야 한다.
- kind 기반 로컬 Kubernetes 클러스터에서 동작해야 한다.

### NFR-002. 안정성

- Kubernetes 리소스 생성 중 실패가 발생해도 DB 상태가 일관되게 남아야 한다.
- 실패한 단계와 원인이 저장되어야 한다.

### NFR-003. 보안

- MVP에서는 인증/인가를 단순화하되, 확장 시 ServiceAccount/RBAC 기반 권한 분리를 고려한다.
- 백엔드가 Kubernetes 클러스터에 접근할 때 필요한 최소 권한만 부여하는 구조로 확장 가능해야 한다.

### NFR-004. 확장성

- Direct Apply 방식에서 Helm/ArgoCD 기반 GitOps 방식으로 확장 가능해야 한다.
- 로컬 kind에서 GKE로 클러스터 대상을 전환할 수 있어야 한다.

### NFR-005. 관측성

- 사용자는 배포 실패 원인을 최소한 Kubernetes Pod 상태와 Event 수준에서 확인할 수 있어야 한다.
- 백엔드는 주요 작업과 예외를 로그로 남겨야 한다.

## 7. MVP 범위

### MVP 1

- 프로젝트 생성/조회 API
- DB 저장
- Namespace 생성
- Deployment 생성
- Service 생성
- Pod 상태 조회

### MVP 2

- ResourceQuota 생성
- Ingress 생성
- Event 조회
- 삭제 기능
- Audit Log

### MVP 3

- React 대시보드
- 프로젝트 생성 폼
- 프로젝트 목록/상세 화면
- Pod/Event 상태 화면
- README/트러블슈팅 문서화

## 8. 성공 기준

| 기준 | 설명 |
|---|---|
| 배포 자동화 | API 호출 한 번으로 Namespace, Deployment, Service가 생성된다. |
| 상태 조회 | Pod 상태와 Kubernetes Event를 API 또는 UI에서 조회할 수 있다. |
| 실패 확인 | 잘못된 이미지명으로 배포 시 ImagePullBackOff 원인을 확인할 수 있다. |
| 삭제 자동화 | 삭제 API 호출 시 생성된 리소스가 정리된다. |
| 문서화 | 로컬 실행 방법, 아키텍처, API 명세, 트러블슈팅이 문서화되어 있다. |

## 9. 향후 확장

- Helm Chart 기반 리소스 템플릿화
- Git Repository에 values.yaml 생성 후 ArgoCD Sync
- ServiceAccount/RBAC 권한 최소화
- GKE 배포 검증
- Prometheus/Grafana 기반 모니터링
- HPA 설정 지원
- Secret/ConfigMap 관리 기능
- 사용자 인증/인가 추가
