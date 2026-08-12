from dataclasses import replace
from threading import RLock

from app.domain import AuditLog, Project


class ProjectAlreadyExists(Exception):
    pass


class DemoCapacityExceeded(Exception):
    pass


class ProjectNotFound(Exception):
    pass


class InMemoryProjectRepository:
    def __init__(self, max_active_projects: int | None) -> None:
        self._max_active_projects = max_active_projects
        self._projects: dict[str, Project] = {}
        self._audit_logs: dict[str, list[AuditLog]] = {}
        self._lock = RLock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(project.capacity_claimed for project in self._projects.values())

    def claim_capacity_and_create(self, project: Project) -> Project:
        with self._lock:
            if project.id in self._projects:
                raise ProjectAlreadyExists(project.id)
            if (
                self._max_active_projects is not None
                and self.active_count >= self._max_active_projects
            ):
                raise DemoCapacityExceeded()

            created_project = replace(project, capacity_claimed=True)
            self._projects[created_project.id] = created_project
            return replace(created_project)

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            project = self._projects.get(project_id)
            return replace(project) if project is not None else None

    def list_projects(self) -> list[Project]:
        with self._lock:
            return [replace(project) for project in self._projects.values()]

    def save_project(self, project: Project) -> Project:
        with self._lock:
            saved_project = replace(project)
            self._projects[saved_project.id] = saved_project
            return replace(saved_project)

    def release_capacity(self, project_id: str) -> Project:
        with self._lock:
            project = self._projects.get(project_id)
            if project is None:
                raise ProjectNotFound(project_id)

            released_project = replace(project, capacity_claimed=False)
            self._projects[project_id] = released_project
            return replace(released_project)

    def append_audit_log(self, log: AuditLog) -> AuditLog:
        with self._lock:
            stored_log = replace(log)
            self._audit_logs.setdefault(stored_log.project_id, []).append(stored_log)
            return replace(stored_log)

    def list_audit_logs(self, project_id: str) -> list[AuditLog]:
        with self._lock:
            return [replace(log) for log in self._audit_logs.get(project_id, [])]

    def health_check(self) -> dict[str, str]:
        return {"status": "ok"}
