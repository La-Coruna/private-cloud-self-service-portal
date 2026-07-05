from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.k8s_client import create_namespace
from app.models import Project, ProjectStatus
from app.schemas import ProjectCreateRequest, ProjectResponse


router = APIRouter(prefix="/api/projects", tags=["projects"])


def build_namespace(service_name: str, environment: str) -> str:
    return f"{service_name}-{environment}"


def _format_namespace_error(result: dict) -> str:
    message = result.get("message") or "Kubernetes namespace creation failed"
    detail = result.get("detail")
    if detail:
        return f"{message}: {detail}"
    return message


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

    if namespace_result["status"] in {"created", "already_exists"}:
        project.status = ProjectStatus.RUNNING
        project.error_message = None
    else:
        project.status = ProjectStatus.FAILED
        project.error_message = _format_namespace_error(namespace_result)

    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.created_at.desc())).scalars())


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
