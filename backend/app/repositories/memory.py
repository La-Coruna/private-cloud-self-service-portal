from dataclasses import replace
from threading import RLock

from app.domain import AuditLog, Project, ProjectStatus
from app.repositories.base import same_creation_spec


class ProjectAlreadyExists(Exception):
    pass


class DemoCapacityExceeded(Exception):
    pass


class ProjectNotFound(Exception):
    pass


class ProjectVersionConflict(Exception):
    def __init__(self, current_project: Project) -> None:
        super().__init__(current_project.id)
        self.current_project = replace(current_project)


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

    def claim_capacity_and_create(
        self,
        project: Project,
        initial_audit: AuditLog | None = None,
    ) -> Project:
        with self._lock:
            if project.id in self._projects:
                existing = self._projects[project.id]
                if (
                    existing.status == ProjectStatus.REQUESTED
                    and same_creation_spec(existing, project)
                ):
                    return replace(existing)
                raise ProjectAlreadyExists(project.id)
            if (
                self._max_active_projects is not None
                and self.active_count >= self._max_active_projects
            ):
                raise DemoCapacityExceeded()

            created_project = replace(project, capacity_claimed=True)
            self._projects[created_project.id] = created_project
            if initial_audit is not None:
                stored_log = replace(initial_audit)
                self._audit_logs.setdefault(created_project.id, []).append(stored_log)
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

    def save_project_if_version(self, project: Project) -> Project:
        with self._lock:
            current = self._projects.get(project.id)
            if current is None:
                raise ProjectNotFound(project.id)
            if current.version != project.version:
                raise ProjectVersionConflict(current)

            saved_project = replace(project, version=project.version + 1)
            self._projects[saved_project.id] = saved_project
            return replace(saved_project)

    def complete_deletion(self, project: Project) -> Project:
        with self._lock:
            current = self._projects.get(project.id)
            if current is None:
                raise ProjectNotFound(project.id)
            if current.status == ProjectStatus.DELETED:
                return replace(current)
            if (
                current.version != project.version
                or current.status != ProjectStatus.DELETING
            ):
                raise ProjectVersionConflict(current)

            deleted = replace(
                project,
                status=ProjectStatus.DELETED,
                error_message=None,
                capacity_claimed=False,
                version=project.version + 1,
            )
            self._projects[deleted.id] = deleted
            return replace(deleted)

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
