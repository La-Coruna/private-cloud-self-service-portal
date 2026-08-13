from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

from app.domain import AuditLog, Project, ProjectStatus
from app.repositories.memory import (
    DemoCapacityExceeded,
    ProjectAlreadyExists,
    ProjectNotFound,
    ProjectVersionConflict,
)
from app.repositories.base import same_creation_spec


def _to_firestore_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _from_firestore_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "namespace": project.namespace,
        "service_name": project.service_name,
        "environment": project.environment,
        "image": project.image,
        "replicas": project.replicas,
        "cpu_request": project.cpu_request,
        "cpu_limit": project.cpu_limit,
        "memory_request": project.memory_request,
        "memory_limit": project.memory_limit,
        "expose_external": project.expose_external,
        "ingress_host": project.ingress_host,
        "status": project.status.value,
        "error_message": project.error_message,
        "capacity_claimed": project.capacity_claimed,
        "created_at": _to_firestore_datetime(project.created_at),
        "updated_at": _to_firestore_datetime(project.updated_at),
        "owner_token": project.owner_token,
        "version": project.version,
    }


def _project_from_dict(data: dict[str, Any]) -> Project:
    return Project(
        id=data["id"],
        namespace=data["namespace"],
        service_name=data["service_name"],
        environment=data["environment"],
        image=data["image"],
        replicas=data["replicas"],
        cpu_request=data["cpu_request"],
        cpu_limit=data["cpu_limit"],
        memory_request=data["memory_request"],
        memory_limit=data["memory_limit"],
        expose_external=data["expose_external"],
        ingress_host=data["ingress_host"],
        status=ProjectStatus(data["status"]),
        error_message=data["error_message"],
        capacity_claimed=data["capacity_claimed"],
        created_at=_from_firestore_datetime(data["created_at"]),
        updated_at=_from_firestore_datetime(data["updated_at"]),
        owner_token=data.get("owner_token", ""),
        version=data.get("version", 0),
    )


def _audit_log_to_dict(log: AuditLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "project_id": log.project_id,
        "action": log.action,
        "status": log.status,
        "message": log.message,
        "created_at": _to_firestore_datetime(log.created_at),
    }


def _audit_log_from_dict(data: dict[str, Any]) -> AuditLog:
    return AuditLog(
        id=data["id"],
        project_id=data["project_id"],
        action=data["action"],
        status=data["status"],
        message=data["message"],
        created_at=_from_firestore_datetime(data["created_at"]),
    )


@firestore.transactional
def _claim(
    transaction,
    project_ref,
    capacity_ref,
    project_data,
    max_active,
    audit_ref=None,
    audit_data=None,
):
    project_snapshot = project_ref.get(transaction=transaction)
    if project_snapshot.exists:
        existing_data = project_snapshot.to_dict()
        existing = _project_from_dict(existing_data)
        proposed = _project_from_dict(project_data)
        if (
            existing.status == ProjectStatus.REQUESTED
            and same_creation_spec(existing, proposed)
        ):
            return existing_data
        raise ProjectAlreadyExists(project_data["id"])

    capacity_snapshot = capacity_ref.get(transaction=transaction)
    active = capacity_snapshot.get("active_count") if capacity_snapshot.exists else 0
    if max_active is not None and active >= max_active:
        raise DemoCapacityExceeded(max_active)

    transaction.set(project_ref, project_data)
    if audit_ref is not None and audit_data is not None:
        transaction.set(audit_ref, audit_data)
    transaction.set(
        capacity_ref,
        {
            "active_count": active + 1,
            "max_active_projects": max_active,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return project_data


@firestore.transactional
def _release(transaction, project_ref, capacity_ref, max_active):
    project_snapshot = project_ref.get(transaction=transaction)
    if not project_snapshot.exists:
        raise ProjectNotFound(project_ref.id)

    project_data = project_snapshot.to_dict()
    if not project_data["capacity_claimed"]:
        return project_data

    capacity_snapshot = capacity_ref.get(transaction=transaction)
    active = capacity_snapshot.get("active_count") if capacity_snapshot.exists else 0
    released_data = {
        **project_data,
        "capacity_claimed": False,
        "version": project_data.get("version", 0) + 1,
    }
    transaction.set(
        project_ref,
        {"capacity_claimed": False, "version": released_data["version"]},
        merge=True,
    )
    transaction.set(
        capacity_ref,
        {
            "active_count": max(active - 1, 0),
            "max_active_projects": max_active,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    return released_data


@firestore.transactional
def _save_if_version(transaction, project_ref, project_data):
    snapshot = project_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise ProjectNotFound(project_ref.id)

    current_data = snapshot.to_dict()
    if current_data.get("version", 0) != project_data.get("version", 0):
        raise ProjectVersionConflict(_project_from_dict(current_data))

    saved_data = {
        **project_data,
        "version": project_data.get("version", 0) + 1,
    }
    transaction.set(project_ref, saved_data)
    return saved_data


@firestore.transactional
def _complete_deletion(
    transaction,
    project_ref,
    capacity_ref,
    project_data,
    max_active,
):
    snapshot = project_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise ProjectNotFound(project_ref.id)

    current_data = snapshot.to_dict()
    if current_data["status"] == ProjectStatus.DELETED.value:
        return current_data
    if (
        current_data.get("version", 0) != project_data.get("version", 0)
        or current_data["status"] != ProjectStatus.DELETING.value
    ):
        raise ProjectVersionConflict(_project_from_dict(current_data))

    capacity_snapshot = None
    if current_data["capacity_claimed"]:
        capacity_snapshot = capacity_ref.get(transaction=transaction)

    deleted_data = {
        **current_data,
        "status": ProjectStatus.DELETED.value,
        "error_message": None,
        "capacity_claimed": False,
        "updated_at": project_data["updated_at"],
        "version": current_data.get("version", 0) + 1,
    }
    transaction.set(project_ref, deleted_data)
    if capacity_snapshot is not None:
        active = (
            capacity_snapshot.get("active_count") if capacity_snapshot.exists else 0
        )
        transaction.set(
            capacity_ref,
            {
                "active_count": max(active - 1, 0),
                "max_active_projects": max_active,
                "updated_at": firestore.SERVER_TIMESTAMP,
            },
            merge=True,
        )
    return deleted_data


class FirestoreProjectRepository:
    def __init__(
        self,
        client: firestore.Client,
        max_active_projects: int | None,
    ) -> None:
        self._client = client
        self._max_active_projects = max_active_projects
        self._projects = client.collection("projects")
        self._capacity = client.document("system/demoCapacity")

    def claim_capacity_and_create(
        self,
        project: Project,
        initial_audit: AuditLog | None = None,
    ) -> Project:
        project_data = _project_to_dict(project)
        project_data["capacity_claimed"] = True
        audit_ref = None
        audit_data = None
        if initial_audit is not None:
            audit_ref = (
                self._projects.document(project.namespace)
                .collection("auditLogs")
                .document(initial_audit.id)
            )
            audit_data = _audit_log_to_dict(initial_audit)
        claimed_data = _claim(
            self._client.transaction(max_attempts=20),
            self._projects.document(project.namespace),
            self._capacity,
            project_data,
            self._max_active_projects,
            audit_ref,
            audit_data,
        )
        return _project_from_dict(claimed_data)

    def get_project(self, project_id: str) -> Project | None:
        snapshot = self._projects.document(project_id).get()
        if not snapshot.exists:
            return None
        return _project_from_dict(snapshot.to_dict())

    def list_projects(self) -> list[Project]:
        projects = [
            _project_from_dict(snapshot.to_dict())
            for snapshot in self._projects.stream()
        ]
        return sorted(projects, key=lambda project: (project.created_at, project.id))

    def save_project(self, project: Project) -> Project:
        project_data = _project_to_dict(project)
        self._projects.document(project.namespace).set(project_data)
        return _project_from_dict(project_data)

    def save_project_if_version(self, project: Project) -> Project:
        project_data = _save_if_version(
            self._client.transaction(max_attempts=20),
            self._projects.document(project.namespace),
            _project_to_dict(project),
        )
        return _project_from_dict(project_data)

    def complete_deletion(self, project: Project) -> Project:
        project_data = _complete_deletion(
            self._client.transaction(max_attempts=20),
            self._projects.document(project.namespace),
            self._capacity,
            _project_to_dict(project),
            self._max_active_projects,
        )
        return _project_from_dict(project_data)

    def release_capacity(self, project_id: str) -> Project:
        project_data = _release(
            self._client.transaction(max_attempts=20),
            self._projects.document(project_id),
            self._capacity,
            self._max_active_projects,
        )
        return _project_from_dict(project_data)

    def append_audit_log(self, log: AuditLog) -> AuditLog:
        log_data = _audit_log_to_dict(log)
        (
            self._projects.document(log.project_id)
            .collection("auditLogs")
            .document(log.id)
            .set(log_data)
        )
        return _audit_log_from_dict(log_data)

    def list_audit_logs(self, project_id: str) -> list[AuditLog]:
        logs = [
            _audit_log_from_dict(snapshot.to_dict())
            for snapshot in self._projects.document(project_id)
            .collection("auditLogs")
            .stream()
        ]
        return sorted(logs, key=lambda log: (log.created_at, log.id))

    def health_check(self) -> dict[str, str]:
        self._capacity.get(timeout=5.0)
        return {"status": "ok"}
