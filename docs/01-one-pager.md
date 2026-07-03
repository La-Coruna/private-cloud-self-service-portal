# 01. 프로젝트 One-Pager

## 프로젝트명

**Kubernetes 기반 Private Cloud Self-Service Portal**

## 한 줄 소개

개발자가 웹 화면 또는 API로 서비스 배포 정보를 입력하면, 플랫폼이 Kubernetes 리소스(Namespace, ResourceQuota, Deployment, Service, Ingress)를 자동 생성하고 배포 상태와 실패 원인을 조회할 수 있게 하는 내부 클라우드 포털 MVP.

## 문제 정의

일반적인 Kubernetes 배포 과정에서는 개발자가 직접 YAML 파일을 작성하고, `kubectl apply`로 적용하며, `kubectl get/describe/logs` 또는 ArgoCD 화면을 통해 상태를 확인해야 한다. 이 방식은 다음과 같은 문제가 있다.

1. Kubernetes 리소스 구조를 깊게 모르는 개발자에게 진입 장벽이 높다.
2. 팀마다 Namespace, Label, ResourceQuota, Ingress 규칙이 달라져 운영 표준이 흐트러질 수 있다.
3. 배포 실패 시 ImagePullBackOff, Pending, Quota 초과, Ingress 설정 오류 등의 원인을 찾기 어렵다.
4. 운영자는 누가 어떤 리소스를 생성·삭제했는지 추적하기 어렵다.

이 프로젝트는 이러한 문제를 해결하기 위해, Kubernetes 배포 작업을 **셀프서비스 포털** 형태로 추상화하고 표준화한다.

## 목표 사용자

### 1차 사용자: 서비스 개발자

- Kubernetes YAML을 직접 작성하지 않고 서비스를 배포하고 싶은 개발자
- 배포 상태와 Pod 오류 원인을 웹에서 확인하고 싶은 개발자
- staging/dev 환경에 빠르게 테스트 서비스를 올리고 싶은 개발자

### 2차 사용자: 플랫폼 운영자

- 조직 표준에 맞게 Namespace, Label, Quota, Ingress 규칙을 강제하고 싶은 운영자
- 생성/삭제 이력을 Audit Log로 추적하고 싶은 운영자
- 리소스 사용량과 배포 실패 원인을 중앙에서 확인하고 싶은 운영자

## 핵심 가치

1. **셀프서비스**: 개발자가 웹 화면/API에서 필요한 값만 입력하면 Kubernetes 리소스가 자동 생성된다.
2. **표준화**: Namespace, Label, Annotation, ResourceQuota, Ingress 규칙을 플랫폼이 통제한다.
3. **운영성**: Pod 상태, Kubernetes Event, 실패 원인을 조회할 수 있다.
4. **추적성**: 신청 정보, 상태 변경, 생성/삭제 이력을 DB에 저장한다.
5. **확장성**: 초기 MVP는 Direct Apply 방식으로 구현하고, 이후 Helm/ArgoCD 기반 GitOps 방식으로 확장할 수 있다.

## MVP 범위

### MVP 1단계: 핵심 배포 자동화

- 프로젝트 생성 API
- 신청 정보 DB 저장
- Namespace 생성
- Deployment 생성
- Service 생성
- Pod 상태 조회

### MVP 2단계: 운영 기능 추가

- ResourceQuota 생성
- Ingress 생성
- Kubernetes Event 조회
- 배포 실패 상태 저장
- 리소스 삭제 기능
- Audit Log 저장

### MVP 3단계: 대시보드 및 포트폴리오 완성

- React 기반 프로젝트 목록 화면
- 프로젝트 생성 화면
- 프로젝트 상세/상태 화면
- Pod/Event/에러 메시지 화면
- README, 아키텍처, 트러블슈팅 문서 정리

## 비범위

MVP에서는 다음 기능을 제외한다.

- 실제 기업 수준의 사용자 인증/인가 고도화
- 멀티 클러스터 관리
- 멀티 테넌트 과금/정산 기능
- 운영급 보안 정책 전체 구현
- HPA, Secret, ConfigMap 고도화 관리
- 운영급 모니터링 스택 전체 구축(Prometheus/Grafana는 확장 기능으로 분리)
- GitOps 자동 커밋/ArgoCD Sync 완전 구현은 선택 확장으로 분리

## 기술 스택

| 영역 | 기술 |
|---|---|
| Backend | Python FastAPI |
| Frontend | React + TypeScript + Vite |
| Database | MariaDB |
| ORM/Migration | SQLAlchemy + Alembic |
| Kubernetes 연동 | kubernetes Python client |
| Local Kubernetes | kind |
| Container | Docker, Docker Compose |
| Ingress | NGINX Ingress Controller |
| 확장 | Helm, ArgoCD, GKE |
| 문서화 | Markdown, README, Architecture Diagram |

## 직무 연결성

이 프로젝트는 Platform Developer 직무에서 요구되는 다음 역량을 직접 보여주는 것을 목표로 한다.

- Python 기반 플랫폼 API 서버 개발
- SQL 기반 신청/상태/로그 데이터 모델링
- JavaScript/TypeScript 기반 대시보드 개발
- Kubernetes 리소스 이해 및 자동화
- Docker 기반 로컬 개발환경 구성
- Private Cloud Product 운영 관점의 표준화, 상태 추적, 장애 원인 조회
- Helm/ArgoCD/GitOps 확장 가능성 설계

## 최종 산출물

- FastAPI 백엔드 애플리케이션
- React 대시보드
- MariaDB 기반 상태 저장소
- kind 기반 로컬 Kubernetes 테스트 환경
- Kubernetes 리소스 자동 생성 기능
- 프로젝트 문서 세트
- README 및 트러블슈팅 기록

## 성공 기준

다음 시나리오가 동작하면 MVP 성공으로 판단한다.

1. 사용자가 `demo-api`, `staging`, `nginx:latest`, CPU/Memory 제한, 외부 공개 여부를 입력한다.
2. 백엔드가 신청 정보를 DB에 저장한다.
3. Kubernetes에 Namespace, Deployment, Service가 생성된다.
4. 외부 공개가 true이면 Ingress가 생성된다.
5. 사용자는 웹/API에서 Pod 상태와 Event를 확인할 수 있다.
6. 이미지 오류 등으로 배포가 실패하면 실패 원인이 표시된다.
7. 삭제 요청 시 플랫폼이 생성한 리소스가 정리되고 Audit Log가 남는다.
