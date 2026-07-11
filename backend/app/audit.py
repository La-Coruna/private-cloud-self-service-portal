from sqlalchemy.orm import Session

from app.models import AuditLog


def create_audit_log(
    db: Session,
    project_id: int,
    action: str,
    status: str,
    message: str | None = None,
) -> AuditLog:
    audit_log = AuditLog(
        project_id=project_id,
        action=action,
        status=status,
        message=message,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log
