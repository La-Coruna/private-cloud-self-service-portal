# Private Cloud Self-Service Portal Docs

이 폴더는 Kubernetes 기반 Private Cloud Self-Service Portal 프로젝트 시작 전 작성한 설계 문서 모음입니다.

## 문서 목록

1. `01-one-pager.md` - 프로젝트 One-Pager
2. `02-prd.md` - 요구사항 정의서 PRD
3. `03-architecture.md` - 시스템 아키텍처 초안
4. `04-k8s-resource-design.md` - Kubernetes 리소스 설계
5. `05-api-spec.md` - API 명세서
6. `06-db-model.md` - DB 모델 초안
7. `07-local-dev-plan.md` - 로컬 개발환경 구성 계획

## 프로젝트 핵심 방향

개발자가 Kubernetes YAML과 kubectl 명령어를 직접 다루지 않아도, 웹 화면 또는 API로 서비스 배포를 신청하고 배포 상태와 실패 원인을 확인할 수 있는 내부 클라우드 포털 MVP를 만든다.

MVP는 FastAPI, React, MariaDB, kind, kubernetes Python client를 기반으로 구현하고, 이후 Helm/ArgoCD/GKE로 확장한다.
