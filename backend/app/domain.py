from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from app.schemas import ProjectCreateRequest


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ProjectStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class PlatformAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    RECOVERING = "RECOVERING"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(slots=True)
class Project:
    id: str
    namespace: str
    service_name: str
    environment: str
    image: str
    replicas: int
    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str
    expose_external: bool
    ingress_host: str | None
    status: ProjectStatus
    error_message: str | None
    capacity_claimed: bool
    created_at: datetime
    updated_at: datetime
    owner_token: str = ""

    @classmethod
    def new(cls, request: "ProjectCreateRequest", namespace: str) -> "Project":
        now = utc_now()
        return cls(
            id=namespace,
            namespace=namespace,
            service_name=request.service_name,
            environment=request.environment,
            image=request.image,
            replicas=request.replicas,
            cpu_request=request.cpu_request,
            cpu_limit=request.cpu_limit,
            memory_request=request.memory_request,
            memory_limit=request.memory_limit,
            expose_external=request.expose_external,
            ingress_host=None,
            status=ProjectStatus.REQUESTED,
            error_message=None,
            capacity_claimed=False,
            created_at=now,
            updated_at=now,
            owner_token=uuid4().hex,
        )


@dataclass(slots=True)
class AuditLog:
    id: str
    project_id: str
    action: str
    status: str
    message: str | None
    created_at: datetime

    @classmethod
    def new(
        cls,
        project_id: str,
        action: str,
        status: str,
        message: str | None = None,
    ) -> "AuditLog":
        return cls(
            id=uuid4().hex,
            project_id=project_id,
            action=action,
            status=status,
            message=message,
            created_at=utc_now(),
        )
