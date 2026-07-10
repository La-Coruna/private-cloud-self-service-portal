from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import ProjectStatus


class ProjectCreateRequest(BaseModel):
    service_name: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    environment: Literal["dev", "staging", "prod"]
    image: str = Field(min_length=3, max_length=255)
    replicas: int = Field(default=1, ge=1, le=5)
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "128Mi"
    memory_limit: str = "512Mi"
    expose_external: bool = False


class ProjectResponse(BaseModel):
    id: int
    service_name: str
    environment: str
    image: str
    replicas: int
    cpu_request: str
    cpu_limit: str
    memory_request: str
    memory_limit: str
    expose_external: bool
    namespace: str
    status: ProjectStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContainerStatusResponse(BaseModel):
    name: str
    image: str
    ready: bool
    restart_count: int
    state: str
    reason: str | None
    message: str | None


class PodResponse(BaseModel):
    name: str
    namespace: str
    phase: str
    pod_ip: str | None
    node_name: str | None
    start_time: str | None
    containers: list[ContainerStatusResponse]


class ProjectEventResponse(BaseModel):
    type: str | None
    reason: str | None
    message: str | None
    count: int | None
    involved_object_kind: str | None
    involved_object_name: str | None
    first_timestamp: str | None
    last_timestamp: str | None
    event_time: str | None
    source_component: str | None
