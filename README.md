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
