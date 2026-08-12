from app.domain import AuditLog
from app.repositories.base import ProjectRepository


def create_audit_log(
    repository: ProjectRepository,
    project_id: str,
    action: str,
    status: str,
    message: str | None = None,
) -> AuditLog:
    return repository.append_audit_log(
        AuditLog.new(
            project_id=project_id,
            action=action,
            status=status,
            message=message,
        )
    )
