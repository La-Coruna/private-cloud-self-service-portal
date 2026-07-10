from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.k8s_client import (
    create_deployment,
    create_namespace,
    create_resource_quota,
    create_service,
    list_project_events,
    list_project_pods,
)
from app.models import Project, ProjectStatus
from app.schemas import ProjectCreateRequest, ProjectEventResponse, ProjectResponse, PodResponse


router = APIRouter(prefix="/api/projects", tags=["projects"])


SUCCESS_STATUSES = {"created", "already_exists"}


def build_namespace(service_name: str, environment: str) -> str:
    return f"{service_name}-{environment}"


def _format_kubernetes_error(result: dict) -> str:
    resource = result.get("resource")
    message = result.get("message") or "Kubernetes resource creation failed"
    detail = result.get("detail")
    prefix = f"{resource}: " if resource else ""
    if detail:
        return f"{prefix}{message}: {detail}"
    return f"{prefix}{message}"


def _mark_failed(project: Project, result: dict, db: Session) -> Project:
    project.status = ProjectStatus.FAILED
    project.error_message = _format_kubernetes_error(result)
    db.commit()
    db.refresh(project)
    return project


def _is_success(result: dict) -> bool:
    return result.get("status") in SUCCESS_STATUSES


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    request: ProjectCreateRequest,
    db: Session = Depends(get_db),
) -> Project:
    namespace = build_namespace(request.service_name, request.environment)
    existing_project = db.execute(
        select(Project).where(Project.namespace == namespace)
    ).scalar_one_or_none()

    if existing_project is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Namespace already requested: {namespace}",
        )

    project = Project(
        service_name=request.service_name,
        environment=request.environment,
        image=request.image,
        replicas=request.replicas,
        cpu_request=request.cpu_request,
        cpu_limit=request.cpu_limit,
        memory_request=request.memory_request,
        memory_limit=request.memory_limit,
        expose_external=request.expose_external,
        namespace=namespace,
        status=ProjectStatus.REQUESTED,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    project.status = ProjectStatus.PROVISIONING
    db.commit()
    db.refresh(project)

    namespace_result = create_namespace(
        namespace,
        project.id,
        request.service_name,
        request.environment,
    )
    if not _is_success(namespace_result):
        return _mark_failed(project, namespace_result, db)

    quota_result = create_resource_quota(
        namespace=namespace,
        project_id=project.id,
        service_name=request.service_name,
        environment=request.environment,
    )
    if not _is_success(quota_result):
        return _mark_failed(project, quota_result, db)

    deployment_result = create_deployment(
        namespace=namespace,
        project_id=project.id,
        service_name=request.service_name,
        environment=request.environment,
        image=request.image,
        replicas=request.replicas,
        cpu_request=request.cpu_request,
        cpu_limit=request.cpu_limit,
        memory_request=request.memory_request,
        memory_limit=request.memory_limit,
    )
    if not _is_success(deployment_result):
        return _mark_failed(project, deployment_result, db)

    service_result = create_service(
        namespace=namespace,
        project_id=project.id,
        service_name=request.service_name,
        environment=request.environment,
    )
    if not _is_success(service_result):
        return _mark_failed(project, service_result, db)

    project.status = ProjectStatus.RUNNING
    project.error_message = None
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.created_at.desc())).scalars())


@router.get("/{project_id}/pods", response_model=list[PodResponse])
def get_project_pods(
    project_id: int,
    db: Session = Depends(get_db),
) -> list[dict]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    try:
        return list_project_pods(namespace=project.namespace, project_id=project.id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

@router.get("/{project_id}/events", response_model=list[ProjectEventResponse])
def get_project_events(
    project_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    try:
        return list_project_events(
            namespace=project.namespace,
            project_id=project.id,
            service_name=project.service_name,
            limit=limit,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )
    return project
