from dataclasses import replace
from typing import Protocol

from app.audit import create_audit_log
from app.config import Settings
from app.domain import PlatformAvailability, Project, ProjectStatus, utc_now
from app.k8s_client import KubernetesUnavailableError
from app.repositories import ProjectNotFound, ProjectRepository
from app.schemas import ProjectCreateRequest


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


class GkeUnavailable(RuntimeError):
    pass


class InvalidLifecycleOperation(RuntimeError):
    pass


class KubernetesGateway(Protocol):
    def create_namespace(
        self,
        namespace: str,
        project_id: str,
        service_name: str,
        environment: str,
    ) -> dict: ...

    def create_resource_quota(self, **kwargs) -> dict: ...

    def create_deployment(self, **kwargs) -> dict: ...

    def create_service(self, **kwargs) -> dict: ...

    def create_ingress(self, **kwargs) -> dict: ...

    def delete_ingress(self, namespace: str, service_name: str) -> dict: ...

    def delete_service(self, namespace: str, service_name: str) -> dict: ...

    def delete_deployment(self, namespace: str, service_name: str) -> dict: ...

    def delete_resource_quota(self, namespace: str) -> dict: ...

    def delete_namespace(self, namespace: str) -> dict: ...

    def list_project_pods(self, namespace: str, project_id: str) -> list[dict]: ...

    def list_project_events(
        self,
        namespace: str,
        project_id: str,
        service_name: str,
        limit: int = 50,
    ) -> list[dict]: ...


class PlatformStatus(Protocol):
    status: PlatformAvailability
    message: str
    creation_allowed: bool


class PlatformStatusService(Protocol):
    def get_status(self) -> PlatformStatus: ...


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


def derive_project_status(
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
        return ProjectStatus.FAILED, _join_status_details(
            pod_summary, waiting_summary, latest_event
        )

    latest_event_reason = events[0].get("reason") if events else None
    if latest_event_reason in FAILURE_EVENT_REASONS:
        return ProjectStatus.FAILED, _join_status_details(waiting_summary, latest_event)

    if not pods:
        return ProjectStatus.PROVISIONING, _join_status_details(
            "No pods found for project yet", latest_event
        )

    return ProjectStatus.PROVISIONING, _join_status_details(waiting_summary, latest_event)


def _format_kubernetes_error(result: dict) -> str:
    resource = result.get("resource")
    message = result.get("message") or "Kubernetes resource creation failed"
    detail = result.get("detail")
    prefix = f"{resource}: " if resource else ""
    if detail:
        return f"{prefix}{message}: {detail}"
    return f"{prefix}{message}"


def _is_create_success(result: dict) -> bool:
    return result.get("status") in SUCCESS_STATUSES


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


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        kubernetes: KubernetesGateway,
        platform_status: PlatformStatusService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.kubernetes = kubernetes
        self.platform_status = platform_status
        self.settings = settings

    def create_project(self, request: ProjectCreateRequest) -> Project:
        self._require_gke(creation=True)
        namespace_prefix = (
            self.settings.demo_namespace_prefix if self.settings.demo_mode else ""
        )
        namespace = f"{namespace_prefix}{request.service_name}-{request.environment}"
        project = self.repository.claim_capacity_and_create(
            Project.new(request=request, namespace=namespace)
        )
        self._audit(
            project,
            "PROJECT_CREATE_REQUESTED",
            "SUCCESS",
            f"Project request saved for namespace={project.namespace}",
        )

        project = self._save(project, status=ProjectStatus.PROVISIONING, error_message=None)
        self._audit(
            project,
            "PROJECT_PROVISIONING_STARTED",
            "SUCCESS",
            "Project provisioning started",
        )

        result = self.kubernetes.create_namespace(
            namespace,
            project.id,
            request.service_name,
            request.environment,
        )
        if not _is_create_success(result):
            return self._fail_create(project, result, "NAMESPACE_CREATE_FAILED")
        self._audit(
            project,
            "NAMESPACE_CREATED",
            "SUCCESS",
            f"Namespace created: {project.namespace}",
        )

        result = self.kubernetes.create_resource_quota(
            namespace=namespace,
            project_id=project.id,
            service_name=request.service_name,
            environment=request.environment,
        )
        if not _is_create_success(result):
            return self._fail_create(project, result, "RESOURCE_QUOTA_CREATE_FAILED")
        self._audit(
            project,
            "RESOURCE_QUOTA_CREATED",
            "SUCCESS",
            f"ResourceQuota created in namespace={project.namespace}",
        )

        result = self.kubernetes.create_deployment(
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
        if not _is_create_success(result):
            return self._fail_create(project, result, "DEPLOYMENT_CREATE_FAILED")
        self._audit(
            project,
            "DEPLOYMENT_CREATED",
            "SUCCESS",
            f"Deployment created: {project.service_name}",
        )

        result = self.kubernetes.create_service(
            namespace=namespace,
            project_id=project.id,
            service_name=request.service_name,
            environment=request.environment,
        )
        if not _is_create_success(result):
            return self._fail_create(project, result, "SERVICE_CREATE_FAILED")
        self._audit(
            project,
            "SERVICE_CREATED",
            "SUCCESS",
            f"Service created: {project.service_name}-svc",
        )

        if request.expose_external:
            ingress_host = (
                f"{request.service_name}-{request.environment}."
                f"{self.settings.ingress_base_domain}"
            )
            result = self.kubernetes.create_ingress(
                namespace=namespace,
                project_id=project.id,
                service_name=request.service_name,
                environment=request.environment,
                host=ingress_host,
            )
            if not _is_create_success(result):
                return self._fail_create(project, result, "INGRESS_CREATE_FAILED")
            project = self._save(project, ingress_host=ingress_host)
            self._audit(
                project,
                "INGRESS_CREATED",
                "SUCCESS",
                f"Ingress created: {ingress_host}",
            )
        else:
            self._audit(
                project,
                "INGRESS_SKIPPED",
                "SUCCESS",
                "External exposure was not requested",
            )

        project = self._save(project, status=ProjectStatus.RUNNING, error_message=None)
        self._audit(
            project,
            "PROJECT_RUNNING",
            "SUCCESS",
            "Project provisioning completed",
        )
        return project

    def list_pods(self, project_id: str) -> list[dict]:
        project = self._get_project(project_id)
        self._require_gke()
        try:
            return self.kubernetes.list_project_pods(
                namespace=project.namespace,
                project_id=project.id,
            )
        except (KubernetesUnavailableError, ConnectionError, TimeoutError) as exc:
            raise GkeUnavailable() from exc

    def list_events(self, project_id: str, limit: int = 50) -> list[dict]:
        project = self._get_project(project_id)
        self._require_gke()
        try:
            return self.kubernetes.list_project_events(
                namespace=project.namespace,
                project_id=project.id,
                service_name=project.service_name,
                limit=limit,
            )
        except (KubernetesUnavailableError, ConnectionError, TimeoutError) as exc:
            raise GkeUnavailable() from exc

    def sync_status(self, project_id: str) -> Project:
        project = self._get_project(project_id)
        if project.status in {ProjectStatus.DELETING, ProjectStatus.DELETED}:
            self._audit(
                project,
                "PROJECT_STATUS_SYNC_SKIPPED",
                "SUCCESS",
                f"Status sync skipped because project is {project.status.value}",
            )
            return project

        self._require_gke()
        previous_status = project.status
        try:
            pods = self.kubernetes.list_project_pods(
                namespace=project.namespace,
                project_id=project.id,
            )
            events = self.kubernetes.list_project_events(
                namespace=project.namespace,
                project_id=project.id,
                service_name=project.service_name,
                limit=50,
            )
        except Exception as exc:
            raise GkeUnavailable(str(exc)) from exc

        next_status, status_detail = derive_project_status(pods, events)
        project = self._save(
            project,
            status=next_status,
            error_message=status_detail if next_status == ProjectStatus.FAILED else None,
        )
        message = f"Kubernetes status synced: {previous_status.value} -> {project.status.value}"
        if status_detail:
            message = f"{message} | {status_detail}"
        self._audit(
            project,
            "PROJECT_STATUS_SYNCED",
            "FAILED" if project.status == ProjectStatus.FAILED else "SUCCESS",
            message,
        )
        return project

    def delete_project(self, project_id: str) -> Project:
        project = self._get_project(project_id)
        if project.status == ProjectStatus.DELETED:
            return project
        if project.status == ProjectStatus.DELETING:
            raise InvalidLifecycleOperation(
                f"Project deletion is already in progress: {project_id}"
            )

        self._require_gke()
        project = self._save(project, status=ProjectStatus.DELETING, error_message=None)
        self._audit(
            project,
            "PROJECT_DELETE_REQUESTED",
            "SUCCESS",
            f"Project delete requested for namespace={project.namespace}",
        )

        delete_results = [
            self.kubernetes.delete_ingress(
                namespace=project.namespace, service_name=project.service_name
            ),
            self.kubernetes.delete_service(
                namespace=project.namespace, service_name=project.service_name
            ),
            self.kubernetes.delete_deployment(
                namespace=project.namespace, service_name=project.service_name
            ),
            self.kubernetes.delete_resource_quota(namespace=project.namespace),
            self.kubernetes.delete_namespace(namespace=project.namespace),
        ]
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
            self._audit(project, action, result_status, message)

        if any(not _is_delete_success(result) for result in delete_results):
            project = self._save(
                project,
                status=ProjectStatus.FAILED,
                error_message=_format_delete_error_message(delete_results),
            )
            self._audit(
                project,
                "PROJECT_DELETE_FAILED",
                "FAILED",
                project.error_message,
            )
            return project

        project = self._save(project, status=ProjectStatus.DELETED, error_message=None)
        if project.capacity_claimed:
            project = self.repository.release_capacity(project.id)
        self._audit(
            project,
            "PROJECT_DELETED",
            "SUCCESS",
            "Project resources deleted successfully",
        )
        return project

    def _get_project(self, project_id: str) -> Project:
        project = self.repository.get_project(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    def _require_gke(self, *, creation: bool = False) -> None:
        try:
            platform = self.platform_status.get_status()
        except Exception as exc:
            raise GkeUnavailable(str(exc)) from exc
        if creation and not platform.creation_allowed:
            raise GkeUnavailable(platform.message)
        if not creation and platform.status == PlatformAvailability.UNAVAILABLE:
            raise GkeUnavailable(platform.message)

    def _save(self, project: Project, **changes) -> Project:
        return self.repository.save_project(
            replace(project, updated_at=utc_now(), **changes)
        )

    def _fail_create(self, project: Project, result: dict, action: str) -> Project:
        failed = self._save(
            project,
            status=ProjectStatus.FAILED,
            error_message=_format_kubernetes_error(result),
        )
        self._audit(failed, action, "FAILED", failed.error_message)
        if failed.capacity_claimed:
            failed = self.repository.release_capacity(failed.id)
        return failed

    def _audit(
        self,
        project: Project,
        action: str,
        status: str,
        message: str | None = None,
    ) -> None:
        create_audit_log(
            repository=self.repository,
            project_id=project.id,
            action=action,
            status=status,
            message=message,
        )
