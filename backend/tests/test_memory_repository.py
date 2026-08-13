import unittest
from dataclasses import replace
from datetime import datetime

from app.domain import AuditLog, Project, ProjectStatus
from app.repositories.memory import (
    DemoCapacityExceeded,
    InMemoryProjectRepository,
    ProjectAlreadyExists,
    ProjectNotFound,
    ProjectVersionConflict,
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
        owner_token=f"owner-token-{project_id}",
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
    def test_claim_capacity_and_create_persists_initial_audit_atomically(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)
        project = make_project("demo-one-staging")
        initial_audit = make_audit_log(
            "audit-requested",
            project.id,
            datetime(2026, 8, 12, 12, 0, 0),
        )

        claimed = repository.claim_capacity_and_create(project, initial_audit)

        self.assertTrue(claimed.capacity_claimed)
        self.assertEqual(repository.active_count, 1)
        self.assertEqual(repository.list_audit_logs(project.id), [initial_audit])

    def test_begin_provisioning_persists_transition_and_audit_once(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)
        requested = repository.claim_capacity_and_create(
            make_project("demo-one-staging")
        )
        provisioning_audit = make_audit_log(
            "audit-provisioning",
            requested.id,
            datetime(2026, 8, 12, 12, 0, 1),
        )

        provisioning = repository.begin_provisioning(
            requested,
            provisioning_audit,
        )

        self.assertEqual(provisioning.status, ProjectStatus.PROVISIONING)
        self.assertEqual(provisioning.version, requested.version + 1)
        self.assertEqual(repository.get_project(requested.id), provisioning)
        self.assertEqual(
            repository.list_audit_logs(requested.id),
            [provisioning_audit],
        )

        with self.assertRaises(ProjectVersionConflict):
            repository.begin_provisioning(requested, provisioning_audit)

        self.assertEqual(repository.active_count, 1)
        self.assertEqual(
            repository.list_audit_logs(requested.id),
            [provisioning_audit],
        )

    def test_stale_status_write_cannot_overwrite_deleting_project(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        stale_project = repository.get_project("demo-one-staging")
        deleting = repository.save_project_if_version(
            replace(stale_project, status=ProjectStatus.DELETING)
        )

        with self.assertRaises(ProjectVersionConflict) as conflict:
            repository.save_project_if_version(
                replace(stale_project, status=ProjectStatus.RUNNING)
            )

        self.assertEqual(conflict.exception.current_project, deleting)
        self.assertEqual(
            repository.get_project("demo-one-staging").status,
            ProjectStatus.DELETING,
        )

    def test_versioned_save_cannot_replace_owner_token(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        current = repository.get_project("demo-one-staging")
        replacement = replace(current, owner_token="different-owner-token")

        with self.assertRaisesRegex(ValueError, "owner_token is immutable"):
            repository.save_project_if_version(replacement)

        self.assertEqual(repository.get_project(current.id), current)

    def test_unversioned_save_cannot_replace_owner_token(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        current = repository.get_project("demo-one-staging")

        with self.assertRaisesRegex(ValueError, "owner_token is immutable"):
            repository.save_project(
                replace(current, owner_token="different-owner-token")
            )

        self.assertEqual(repository.get_project(current.id), current)

    def test_complete_deletion_releases_capacity_once_and_is_idempotent(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        project = repository.get_project("demo-one-staging")
        deleting = repository.save_project_if_version(
            replace(project, status=ProjectStatus.DELETING)
        )

        first = repository.complete_deletion(deleting)
        second = repository.complete_deletion(deleting)

        self.assertEqual(first, second)
        self.assertEqual(second.status, ProjectStatus.DELETED)
        self.assertFalse(second.capacity_claimed)
        self.assertEqual(repository.active_count, 0)

    def test_complete_deletion_requires_deleting_status(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        requested = repository.get_project("demo-one-staging")

        with self.assertRaises(ProjectVersionConflict):
            repository.complete_deletion(requested)

        self.assertEqual(repository.active_count, 1)
        self.assertEqual(
            repository.get_project(requested.id).status,
            ProjectStatus.REQUESTED,
        )

    def test_claim_capacity_and_create_is_atomic(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=1)

        repository.claim_capacity_and_create(make_project("demo-one-staging"))

        with self.assertRaises(DemoCapacityExceeded):
            repository.claim_capacity_and_create(make_project("demo-two-staging"))

        self.assertEqual(repository.active_count, 1)
        self.assertIsNone(repository.get_project("demo-two-staging"))

    def test_claim_rejects_requested_duplicate_with_different_spec(self) -> None:
        repository = seeded_repository(capacity_claimed=True)
        conflicting = make_project("demo-one-staging")
        conflicting.image = "caddy:2.8"

        with self.assertRaises(ProjectAlreadyExists):
            repository.claim_capacity_and_create(conflicting)

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
