from app.domain import AuditLog
from app.repositories.base import ProjectRepository


def create_audit_log(
    repository: ProjectRepository | None = None,
    project_id: str | int | None = None,
    action: str | None = None,
    status: str | None = None,
    message: str | None = None,
    **legacy,
) -> AuditLog:
    if repository is not None:
        return repository.append_audit_log(
            AuditLog.new(str(project_id), str(action), str(status), message)
        )

    # Temporary compatibility for the SQLAlchemy router retained until Task 6.
    db = legacy["db"]
    from app.models import AuditLog as SqlAuditLog

    audit_log = SqlAuditLog(
        project_id=project_id,
        action=action,
        status=status,
        message=message,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log
