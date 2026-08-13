import os
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from google.cloud import firestore

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.domain import AuditLog, Project, ProjectStatus
from app.repositories import DemoCapacityExceeded, ProjectVersionConflict
from app.repositories.firestore import FirestoreProjectRepository


@unittest.skipUnless(
    os.environ.get("FIRESTORE_EMULATOR_HOST"),
    "FIRESTORE_EMULATOR_HOST is required for Firestore emulator integration tests",
)
class FirestoreEmulatorIntegrationTest(unittest.TestCase):
    project_id = "serverless-portal-local"

    def setUp(self) -> None:
        self.client = firestore.Client(project=self.project_id)
        self.repository = FirestoreProjectRepository(
            client=self.client,
            max_active_projects=3,
        )

    def make_project(
        self,
        project_id: str,
        *,
        created_at: datetime | None = None,
    ) -> Project:
        created_at = created_at or datetime(2026, 8, 12, 9, 30, 0)
        return Project(
            id=project_id,
            namespace=project_id,
            service_name=project_id,
            environment="integration",
            image="nginx:1.27",
            replicas=1,
            cpu_request="250m",
            cpu_limit="1",
            memory_request="256Mi",
            memory_limit="1Gi",
            expose_external=True,
            ingress_host=f"{project_id}.apps.example.test",
            status=ProjectStatus.RUNNING,
            error_message=None,
            capacity_claimed=True,
            created_at=created_at,
            updated_at=created_at.replace(second=1),
        )

    def test_four_concurrent_claims_allow_exactly_three_projects(self) -> None:
        self.client.document("system/demoCapacity").set(
            {"active_count": 0, "max_active_projects": 3}
        )
        run_id = uuid4().hex
        projects = [
            self.make_project(f"integration-{run_id}-{index}")
            for index in range(4)
        ]

        claimed_projects = []
        capacity_errors = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(self.repository.claim_capacity_and_create, project)
                for project in projects
            ]
            for future in as_completed(futures):
                try:
                    claimed_projects.append(future.result())
                except DemoCapacityExceeded as error:
                    capacity_errors.append(error)

        self.assertEqual(len(claimed_projects), 3)
        self.assertEqual(len(capacity_errors), 1)
        claimed_ids = {project.id for project in claimed_projects}
        self.assertEqual(len(claimed_ids), 3)
        self.assertTrue(
            claimed_ids.issubset({project.id for project in projects})
        )

    def test_concurrent_delete_owners_release_capacity_exactly_once(self) -> None:
        self.client.document("system/demoCapacity").set(
            {"active_count": 0, "max_active_projects": 3}
        )
        project = self.make_project(f"delete-race-{uuid4().hex}")
        claimed = self.repository.claim_capacity_and_create(project)

        acquired = []
        conflicts = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self.repository.save_project_if_version,
                    replace(claimed, status=ProjectStatus.DELETING),
                )
                for _ in range(2)
            ]
            for future in as_completed(futures):
                try:
                    acquired.append(future.result())
                except ProjectVersionConflict as error:
                    conflicts.append(error)

        self.assertEqual(len(acquired), 1)
        self.assertEqual(len(conflicts), 1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            completed = list(
                executor.map(
                    self.repository.complete_deletion,
                    [acquired[0], acquired[0]],
                )
            )

        self.assertTrue(
            all(project.status == ProjectStatus.DELETED for project in completed)
        )
        self.assertTrue(all(not project.capacity_claimed for project in completed))
        self.assertEqual(
            self.client.document("system/demoCapacity").get().get("active_count"),
            0,
        )

    def test_stale_sync_cannot_overwrite_delete_transaction(self) -> None:
        self.client.document("system/demoCapacity").set(
            {"active_count": 0, "max_active_projects": 3}
        )
        project = self.make_project(f"delete-sync-race-{uuid4().hex}")
        claimed = self.repository.claim_capacity_and_create(project)
        deleting = self.repository.save_project_if_version(
            replace(claimed, status=ProjectStatus.DELETING)
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            completing = executor.submit(self.repository.complete_deletion, deleting)
            stale_sync = executor.submit(
                self.repository.save_project_if_version,
                replace(claimed, status=ProjectStatus.RUNNING),
            )
            deleted = completing.result()
            with self.assertRaises(ProjectVersionConflict):
                stale_sync.result()

        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        self.assertFalse(deleted.capacity_claimed)
        self.assertEqual(self.repository.get_project(project.id), deleted)
        self.assertEqual(
            self.client.document("system/demoCapacity").get().get("active_count"),
            0,
        )

    def test_project_and_audit_logs_round_trip_through_new_repository(self) -> None:
        run_id = uuid4().hex
        project = self.make_project(f"round-trip-{run_id}")
        earlier = AuditLog(
            id=f"{run_id}-earlier",
            project_id=project.id,
            action="PROJECT_REQUESTED",
            status="SUCCESS",
            message="request accepted",
            created_at=datetime(2026, 8, 12, 10, 0, 0),
        )
        later = AuditLog(
            id=f"{run_id}-later",
            project_id=project.id,
            action="PROJECT_RUNNING",
            status="SUCCESS",
            message="workload ready",
            created_at=datetime(2026, 8, 12, 10, 0, 1),
        )

        self.repository.save_project(project)
        self.repository.append_audit_log(later)
        self.repository.append_audit_log(earlier)

        reloaded_repository = FirestoreProjectRepository(
            client=firestore.Client(project=self.project_id),
            max_active_projects=3,
        )
        self.assertEqual(reloaded_repository.get_project(project.id), project)
        self.assertEqual(
            reloaded_repository.list_audit_logs(project.id),
            [earlier, later],
        )


if __name__ == "__main__":
    unittest.main()
