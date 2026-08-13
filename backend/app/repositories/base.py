from typing import Protocol

from app.domain import AuditLog, Project


def same_creation_spec(existing: Project, proposed: Project) -> bool:
    return (
        existing.namespace,
        existing.service_name,
        existing.environment,
        existing.image,
        existing.replicas,
        existing.cpu_request,
        existing.cpu_limit,
        existing.memory_request,
        existing.memory_limit,
        existing.expose_external,
    ) == (
        proposed.namespace,
        proposed.service_name,
        proposed.environment,
        proposed.image,
        proposed.replicas,
        proposed.cpu_request,
        proposed.cpu_limit,
        proposed.memory_request,
        proposed.memory_limit,
        proposed.expose_external,
    )


class ProjectRepository(Protocol):
    def claim_capacity_and_create(
        self,
        project: Project,
        initial_audit: AuditLog | None = None,
    ) -> Project: ...

    def begin_provisioning(
        self,
        project: Project,
        audit: AuditLog,
    ) -> Project: ...

    def get_project(self, project_id: str) -> Project | None: ...

    def list_projects(self) -> list[Project]: ...

    def save_project(self, project: Project) -> Project: ...

    def save_project_if_version(self, project: Project) -> Project: ...

    def complete_deletion(self, project: Project) -> Project: ...

    def release_capacity(self, project_id: str) -> Project: ...

    def append_audit_log(self, log: AuditLog) -> AuditLog: ...

    def list_audit_logs(self, project_id: str) -> list[AuditLog]: ...

    def health_check(self) -> dict[str, str]: ...
