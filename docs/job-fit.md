# Hyundai AutoEver Platform Developer Job Fit

This document maps the Private Cloud Self-Service Portal MVP to the Hyundai AutoEver Platform Developer role.

## Fit Summary

| Role expectation | Project evidence |
| --- | --- |
| Python backend development | FastAPI project lifecycle APIs |
| SQL/database usage | MariaDB models for projects and audit logs |
| JavaScript/TypeScript frontend | React dashboard for developers |
| Kubernetes platform work | Namespace, ResourceQuota, Deployment, Service, Ingress automation |
| Container/local infra | Docker Compose and kind cluster setup |
| Network understanding | Service plus Ingress routing model |
| Operations traceability | Pod, Event, Audit Log views |
| Incident diagnosis | waiting reason, Event, and status sync workflow |
| Future platform direction | Helm, ArgoCD, GKE, RBAC, Prometheus/Grafana extension path |

## Python FastAPI

The backend is not a simple CRUD server. `POST /api/projects` stores a request, calls Kubernetes APIs in order, records success or failure, and returns the platform state. `DELETE /api/projects/{id}` performs cleanup in dependency order. `POST /api/projects/{id}/sync-status` reconciles DB status with live Kubernetes state.

Relevant capabilities:

- REST API design.
- request/response schema modeling.
- error handling.
- platform workflow orchestration.
- test coverage with unittest and mocks for Kubernetes calls.

## SQL and MariaDB

MariaDB stores project requests, namespace and ingress metadata, lifecycle status, error messages, and audit logs. This gives the platform a durable source of truth beyond live Kubernetes objects.

Relevant capabilities:

- relational data modeling.
- lifecycle status tracking.
- audit table design.
- SQLAlchemy ORM usage.

## JavaScript and TypeScript React

The React dashboard gives developers a self-service interface for project creation, list/detail views, Pod/Event/Audit Log inspection, deletion, and status refresh.

Relevant capabilities:

- TypeScript data contracts.
- API client separation.
- TanStack Query server-state management.
- route-based dashboard UI.
- Vitest and Testing Library coverage.

## Kubernetes Resource Automation

The backend uses the Kubernetes Python client to automate:

- Namespace creation.
- ResourceQuota creation.
- Deployment creation.
- Service creation.
- Ingress creation.
- reverse-order deletion.

This demonstrates understanding of Kubernetes object relationships and platform-level resource lifecycle management.

## Docker and kind Local Cluster

The project can be demonstrated locally with Docker Compose and kind. This makes the portfolio reproducible and shows practical development environment ownership.

Relevant capabilities:

- local DB via Docker Compose.
- local Kubernetes via kind.
- ingress-nginx installation.
- hostPort and port-forward troubleshooting.

## Ingress and Service Networking

The platform separates internal and external access:

```text
Browser -> Ingress -> Service -> Pod
```

Service is created as ClusterIP for internal routing. Ingress is created only when `expose_external=true`. The local demo uses `localtest.me` and port `8080` for browser validation.

## Audit Log and Operational Traceability

The system writes Audit Logs for project request, provisioning start, each Kubernetes resource step, status sync, failure, deletion steps, and final deletion. This is important for platform operations because users and operators need to know which step failed and why.

## Status Sync and Incident Diagnosis

A Kubernetes Deployment being accepted does not guarantee that its Pods are healthy. The project handles this by adding `sync-status`:

- list Pods by project labels.
- inspect Pod phase.
- inspect container waiting reason.
- inspect latest Kubernetes Events.
- update DB status to `RUNNING`, `FAILED`, or `PROVISIONING`.
- write an Audit Log entry.

This directly addresses real platform status drift and failure diagnosis problems.

## Helm and ArgoCD Extension Path

The MVP currently creates Kubernetes objects directly through the Python client. A production-oriented extension could introduce:

- Helm charts for standardized workload templates.
- ArgoCD for GitOps reconciliation and drift detection.
- GKE for managed Kubernetes deployment.
- RBAC for team/user-level access control.
- Prometheus/Grafana for platform observability.

## Portfolio Pitch

This project is a small Internal Developer Platform MVP. It connects backend API development, SQL persistence, React dashboard implementation, Kubernetes resource automation, Ingress networking, auditability, and incident response. That combination is directly aligned with Platform Developer work.
