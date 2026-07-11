from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import create_audit_log
from app.db import get_db
from app.k8s_client import (
    build_ingress_host,
    create_deployment,
    create_ingress,
    create_namespace,
    create_resource_quota,
    create_service,
    delete_project_resources,
    list_project_events,
    list_project_pods,
)
from app.models import AuditLog, Project, ProjectStatus
from app.schemas import AuditLogResponse, ProjectCreateRequest, ProjectEventResponse, ProjectResponse, PodResponse


router = APIRouter(prefix="/api/projects", tags=["projects"])


SUCCESS_STATUSES = {"created", "already_exists"}
FAILURE_WAITING_REASONS = {
    "CrashLoopBackOff",
    "CreateContainerConfigError",
    "CreateContainerError",
    "ErrImagePull",
    "ImagePullBackOff",
    "InvalidImageName",
    "RunContainerError",
}
FAILURE_EVENT_REASONS = {"BackOff", "Failed", "FailedCreate", "FailedMount", "FailedScheduling"}


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


def _join_status_details(*details: str | None) -> str | None:
    useful_details = [detail for detail in details if detail]
    return " | ".join(useful_details) if useful_details else None


def _latest_event_summary(events: list[dict]) -> str | None:
    if not events:
        return None
    event = events[0]
    reason = event.get("reason") or "Unknown"
    message = event.get("message")
    if message:
        return f"Latest event {reason}: {message}"
    return f"Latest event {reason}"


def _first_waiting_container_summary(pods: list[dict]) -> tuple[str | None, str | None]:
    for pod in pods:
        pod_name = pod.get("name") or "unknown-pod"
        for container in pod.get("containers", []):
            if container.get("state") != "waiting":
                continue
            reason = container.get("reason")
            if not reason:
                continue
            container_name = container.get("name") or "unknown-container"
            message = container.get("message")
            summary = f"{pod_name}/{container_name} waiting: {reason}"
            if message:
                summary = f"{summary} - {message}"
            return reason, summary
    return None, None


def _all_pods_ready(pods: list[dict]) -> bool:
    if not pods:
        return False
    for pod in pods:
        if pod.get("phase") != "Running":
            return False
        containers = pod.get("containers", [])
        if not containers or any(not container.get("ready") for container in containers):
            return False
    return True


def _derive_project_status_from_kubernetes(
    pods: list[dict],
    events: list[dict],
) -> tuple[ProjectStatus, str | None]:
    latest_event = _latest_event_summary(events)
    if _all_pods_ready(pods):
        return ProjectStatus.RUNNING, None

    waiting_reason, waiting_summary = _first_waiting_container_summary(pods)
    if waiting_reason in FAILURE_WAITING_REASONS:
        return ProjectStatus.FAILED, _join_status_details(waiting_summary, latest_event)

    failed_pod = next((pod for pod in pods if pod.get("phase") == "Failed"), None)
    if failed_pod is not None:
        pod_summary = f"Pod {failed_pod.get('name') or 'unknown-pod'} is Failed"
        return ProjectStatus.FAILED, _join_status_details(pod_summary, waiting_summary, latest_event)

    latest_event_reason = events[0].get("reason") if events else None
    if latest_event_reason in FAILURE_EVENT_REASONS:
        return ProjectStatus.FAILED, _join_status_details(waiting_summary, latest_event)

    if not pods:
        return ProjectStatus.PROVISIONING, _join_status_details("No pods found for project yet", latest_event)

    return ProjectStatus.PROVISIONING, _join_status_details(waiting_summary, latest_event)


def _mark_failed(project: Project, result: dict, db: Session) -> Project:
    project.status = ProjectStatus.FAILED
    project.error_message = _format_kubernetes_error(result)
    db.commit()
    db.refresh(project)
    return project


def _is_success(result: dict) -> bool:
    return result.get("status") in SUCCESS_STATUSES


def _log_project_event(
    db: Session,
    project: Project,
    action: str,
    status: str,
    message: str | None = None,
) -> None:
    create_audit_log(
        db=db,
        project_id=project.id,
        action=action,
        status=status,
        message=message,
    )


def _mark_failed_with_audit(
    project: Project,
    result: dict,
    db: Session,
    action: str,
) -> Project:
    failed_project = _mark_failed(project, result, db)
    _log_project_event(
        db=db,
        project=failed_project,
        action=action,
        status="FAILED",
        message=failed_project.error_message,
    )
    return failed_project

def _is_delete_success(result: dict) -> bool:
    return result.get("status") in {"deleted", "not_found"}


def _format_delete_error_message(results: list[dict]) -> str:
    messages = []
    for result in results:
        if _is_delete_success(result):
            continue
        resource = result.get("resource", "unknown")
        name = result.get("name", "unknown")
        message = result.get("message") or "Unknown Kubernetes error"
        detail = result.get("detail")
        if detail:
            messages.append(f"{resource}/{name}: {message} - {detail}")
        else:
            messages.append(f"{resource}/{name}: {message}")
    return " | ".join(messages)



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

    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_CREATE_REQUESTED",
        status="SUCCESS",
        message=f"Project request saved for namespace={project.namespace}",
    )

    project.status = ProjectStatus.PROVISIONING
    db.commit()
    db.refresh(project)

    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_PROVISIONING_STARTED",
        status="SUCCESS",
        message="Project provisioning started",
    )

    namespace_result = create_namespace(
        namespace,
        project.id,
        request.service_name,
        request.environment,
    )
    if not _is_success(namespace_result):
        return _mark_failed_with_audit(
            project,
            namespace_result,
            db,
            "NAMESPACE_CREATE_FAILED",
        )

    _log_project_event(
        db=db,
        project=project,
        action="NAMESPACE_CREATED",
        status="SUCCESS",
        message=f"Namespace created: {project.namespace}",
    )

    quota_result = create_resource_quota(
        namespace=namespace,
        project_id=project.id,
        service_name=request.service_name,
        environment=request.environment,
    )
    if not _is_success(quota_result):
        return _mark_failed_with_audit(
            project,
            quota_result,
            db,
            "RESOURCE_QUOTA_CREATE_FAILED",
        )

    _log_project_event(
        db=db,
        project=project,
        action="RESOURCE_QUOTA_CREATED",
        status="SUCCESS",
        message=f"ResourceQuota created in namespace={project.namespace}",
    )

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
        return _mark_failed_with_audit(
            project,
            deployment_result,
            db,
            "DEPLOYMENT_CREATE_FAILED",
        )

    _log_project_event(
        db=db,
        project=project,
        action="DEPLOYMENT_CREATED",
        status="SUCCESS",
        message=f"Deployment created: {project.service_name}",
    )

    service_result = create_service(
        namespace=namespace,
        project_id=project.id,
        service_name=request.service_name,
        environment=request.environment,
    )
    if not _is_success(service_result):
        return _mark_failed_with_audit(
            project,
            service_result,
            db,
            "SERVICE_CREATE_FAILED",
        )

    _log_project_event(
        db=db,
        project=project,
        action="SERVICE_CREATED",
        status="SUCCESS",
        message=f"Service created: {project.service_name}-svc",
    )

    if request.expose_external:
        ingress_host = build_ingress_host(request.service_name, request.environment)
        ingress_result = create_ingress(
            namespace=namespace,
            project_id=project.id,
            service_name=request.service_name,
            environment=request.environment,
            host=ingress_host,
        )
        if not _is_success(ingress_result):
            return _mark_failed_with_audit(
                project,
                ingress_result,
                db,
                "INGRESS_CREATE_FAILED",
            )

        project.ingress_host = ingress_host
        db.commit()
        db.refresh(project)

        _log_project_event(
            db=db,
            project=project,
            action="INGRESS_CREATED",
            status="SUCCESS",
            message=f"Ingress created: {ingress_host}",
        )
    else:
        _log_project_event(
            db=db,
            project=project,
            action="INGRESS_SKIPPED",
            status="SUCCESS",
            message="External exposure was not requested",
        )

    project.status = ProjectStatus.RUNNING
    project.error_message = None
    db.commit()
    db.refresh(project)

    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_RUNNING",
        status="SUCCESS",
        message="Project provisioning completed",
    )

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


@router.post("/{project_id}/sync-status", response_model=ProjectResponse)
def sync_project_status(
    project_id: int,
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    if project.status in {ProjectStatus.DELETING, ProjectStatus.DELETED}:
        _log_project_event(
            db=db,
            project=project,
            action="PROJECT_STATUS_SYNC_SKIPPED",
            status="SUCCESS",
            message=f"Status sync skipped because project is {project.status.value}",
        )
        return project

    previous_status = project.status
    try:
        pods = list_project_pods(namespace=project.namespace, project_id=project.id)
        events = list_project_events(
            namespace=project.namespace,
            project_id=project.id,
            service_name=project.service_name,
            limit=50,
        )
    except RuntimeError as exc:
        project.status = ProjectStatus.FAILED
        project.error_message = str(exc)
        db.commit()
        db.refresh(project)
        _log_project_event(
            db=db,
            project=project,
            action="PROJECT_STATUS_SYNC_FAILED",
            status="FAILED",
            message=project.error_message,
        )
        return project

    next_status, status_detail = _derive_project_status_from_kubernetes(pods, events)
    project.status = next_status
    project.error_message = status_detail if next_status == ProjectStatus.FAILED else None
    db.commit()
    db.refresh(project)

    message = f"Kubernetes status synced: {previous_status.value} -> {project.status.value}"
    if status_detail:
        message = f"{message} | {status_detail}"
    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_STATUS_SYNCED",
        status="FAILED" if project.status == ProjectStatus.FAILED else "SUCCESS",
        message=message,
    )

    return project


@router.delete("/{project_id}", response_model=ProjectResponse)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )

    if project.status == ProjectStatus.DELETED:
        return project

    project.status = ProjectStatus.DELETING
    project.error_message = None
    db.commit()
    db.refresh(project)

    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_DELETE_REQUESTED",
        status="SUCCESS",
        message=f"Project delete requested for namespace={project.namespace}",
    )

    delete_results = delete_project_resources(
        namespace=project.namespace,
        service_name=project.service_name,
    )

    delete_action_by_resource = {
        "ingress": "INGRESS_DELETED",
        "service": "SERVICE_DELETED",
        "deployment": "DEPLOYMENT_DELETED",
        "resourcequota": "RESOURCE_QUOTA_DELETED",
        "namespace": "NAMESPACE_DELETED",
    }

    for result in delete_results:
        resource = result.get("resource", "unknown")
        name = result.get("name", "unknown")
        result_status = "SUCCESS" if _is_delete_success(result) else "FAILED"
        action = delete_action_by_resource.get(resource, "K8S_RESOURCE_DELETED")
        message = f"{resource}/{name}: {result.get('status')}"
        if result.get("message"):
            message = f"{message} - {result.get('message')}"
        _log_project_event(
            db=db,
            project=project,
            action=action,
            status=result_status,
            message=message,
        )

    if any(not _is_delete_success(result) for result in delete_results):
        project.status = ProjectStatus.FAILED
        project.error_message = _format_delete_error_message(delete_results)
        db.commit()
        db.refresh(project)

        _log_project_event(
            db=db,
            project=project,
            action="PROJECT_DELETE_FAILED",
            status="FAILED",
            message=project.error_message,
        )

        return project

    project.status = ProjectStatus.DELETED
    project.error_message = None
    db.commit()
    db.refresh(project)

    _log_project_event(
        db=db,
        project=project,
        action="PROJECT_DELETED",
        status="SUCCESS",
        message="Project resources deleted successfully",
    )

    return project


@router.get("/{project_id}/audit-logs", response_model=list[AuditLogResponse])
def get_project_audit_logs(
    project_id: int,
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project not found: {project_id}",
        )
    return list(
        db.execute(
            select(AuditLog)
            .where(AuditLog.project_id == project_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).scalars()
    )

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
