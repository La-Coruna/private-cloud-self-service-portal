import enum
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ProjectStatus(str, enum.Enum):
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(30), nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    replicas: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cpu_request: Mapped[str] = mapped_column(String(30), nullable=False)
    cpu_limit: Mapped[str] = mapped_column(String(30), nullable=False)
    memory_request: Mapped[str] = mapped_column(String(30), nullable=False)
    memory_limit: Mapped[str] = mapped_column(String(30), nullable=False)
    expose_external: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    namespace: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="project_status",
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=ProjectStatus.REQUESTED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
        nullable=False,
    )
