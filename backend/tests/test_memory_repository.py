import unittest
from datetime import datetime

from app.domain import AuditLog, Project, ProjectStatus
from app.repositories.memory import (
    DemoCapacityExceeded,
    InMemoryProjectRepository,
    ProjectAlreadyExists,
    ProjectNotFound,
)


def make_project(project_id: str) -> Project:
    created_at = datetime(2026, 8, 12, 12, 0, 0)
    return Project(
        id=project_id,
        namespace=project_id,
        service_name="demo",
        environment="staging",
        image="nginx:1.27",
        replicas=1,
        cpu_request="250m",
        cpu_limit="1",
        memory_request="256Mi",
        memory_limit="1Gi",
        expose_external=False,
        ingress_host=None,
        status=ProjectStatus.REQUESTED,
        error_message=None,
        capacity_claimed=False,
        created_at=created_at,
        updated_at=created_at,
    )


def make_audit_log(log_id: str, project_id: str, created_at: datetime) -> AuditLog:
    return AuditLog(
        id=log_id,
        project_id=project_id,
        action="PROJECT_CREATED",
        status="SUCCESS",
        message=None,
        created_at=created_at,
    )


def seeded_repository(*, capacity_claimed: bool = False) -> InMemoryProjectRepository:
    repository = InMemoryProjectRepository(max_active_projects=2)
    project = make_project("demo-one-staging")
    if capacity_claimed:
        repository.claim_capacity_and_create(project)
    else:
        repository.save_project(project)
    return repository


class InMemoryProjectRepositoryTests(unittest.TestCase):
    def test_claim_capacity_and_create_is_atomic(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)

        repository.claim_capacity_and_create(make_project("demo-one-staging"))

        with self.assertRaises(DemoCapacityExceeded):
            repository.claim_capacity_and_create(make_project("demo-two-staging"))

        self.assertEqual(repository.active_count, 1)
        self.assertIsNone(repository.get_project("demo-two-staging"))

    def test_claim_capacity_and_create_rejects_duplicate_without_consuming_capacity(self) -> None:
        repository = seeded_repository(capacity_claimed=True)

        with self.assertRaises(ProjectAlreadyExists):
            repository.claim_capacity_and_create(make_project("demo-one-staging"))

        self.assertEqual(repository.active_count, 1)

    def test_release_capacity_is_idempotent(self) -> None:
        repository = seeded_repository(capacity_claimed=True)

        repository.release_capacity("demo-one-staging")
        repository.release_capacity("demo-one-staging")

        self.assertEqual(repository.active_count, 0)
        self.assertFalse(repository.get_project("demo-one-staging").capacity_claimed)

    def test_repository_returns_defensive_project_copies(self) -> None:
        repository = seeded_repository()

        fetched_project = repository.get_project("demo-one-staging")
        fetched_project.status = ProjectStatus.FAILED

        self.assertEqual(
            repository.get_project("demo-one-staging").status,
            ProjectStatus.REQUESTED,
        )

    def test_save_project_updates_an_existing_project(self) -> None:
        repository = seeded_repository()
        project = repository.get_project("demo-one-staging")
        project.status = ProjectStatus.RUNNING

        saved_project = repository.save_project(project)

        self.assertEqual(saved_project.status, ProjectStatus.RUNNING)
        self.assertEqual(
            repository.get_project("demo-one-staging").status,
            ProjectStatus.RUNNING,
        )

    def test_list_projects_preserves_creation_order(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=2)
        repository.save_project(make_project("demo-one-staging"))
        repository.save_project(make_project("demo-two-staging"))

        projects = repository.list_projects()

        self.assertEqual([project.id for project in projects], ["demo-one-staging", "demo-two-staging"])

    def test_release_capacity_rejects_unknown_project(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)

        with self.assertRaises(ProjectNotFound):
            repository.release_capacity("missing-project")

    def test_audit_logs_are_listed_in_append_order_for_a_project(self) -> None:
        repository = seeded_repository()
        first_log = make_audit_log(
            "audit-1", "demo-one-staging", datetime(2026, 8, 12, 12, 0, 0)
        )
        second_log = make_audit_log(
            "audit-2", "demo-one-staging", datetime(2026, 8, 12, 12, 0, 1)
        )
        repository.append_audit_log(first_log)
        repository.append_audit_log(second_log)

        audit_logs = repository.list_audit_logs("demo-one-staging")

        self.assertEqual([log.id for log in audit_logs], ["audit-1", "audit-2"])

    def test_health_check_reports_an_healthy_repository(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)

        self.assertEqual(repository.health_check(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
