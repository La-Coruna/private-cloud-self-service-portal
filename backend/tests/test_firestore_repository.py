import copy
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from app.config import Settings
from app.domain import AuditLog, Project, ProjectStatus
from app.repositories import (
    DemoCapacityExceeded,
    ProjectAlreadyExists,
    ProjectNotFound,
)
from app.repositories.firestore import FirestoreProjectRepository


class FakeDocumentSnapshot:
    def __init__(self, reference, data):
        self.reference = reference
        self.id = reference.id
        self._data = copy.deepcopy(data)
        self.exists = data is not None

    def get(self, field_path):
        if not self.exists:
            raise KeyError(field_path)
        return self._data[field_path]

    def to_dict(self):
        return copy.deepcopy(self._data) if self.exists else None


class FakeDocumentReference:
    def __init__(self, client, path):
        self._client = client
        self.path = path
        self.id = path.rsplit("/", 1)[-1]

    def collection(self, collection_id):
        return FakeCollectionReference(self._client, f"{self.path}/{collection_id}")

    def get(self, transaction=None):
        del transaction
        return FakeDocumentSnapshot(self, self._client._documents.get(self.path))

    def set(self, document_data, merge=False):
        self._client._set(self.path, document_data, merge=merge)


class FakeCollectionReference:
    def __init__(self, client, path):
        self._client = client
        self.path = path

    def document(self, document_id):
        return FakeDocumentReference(self._client, f"{self.path}/{document_id}")

    def stream(self):
        prefix = f"{self.path}/"
        direct_child_depth = self.path.count("/") + 1
        for path, data in self._client._documents.items():
            if path.startswith(prefix) and path.count("/") == direct_child_depth:
                yield FakeDocumentSnapshot(
                    FakeDocumentReference(self._client, path),
                    data,
                )


class FakeTransaction:
    def __init__(self, client):
        self._client = client
        self._writes = []
        self._max_attempts = 1
        self._read_only = False
        self._id = None

    def _clean_up(self):
        self._writes.clear()
        self._id = None

    def _begin(self, retry_id=None):
        del retry_id
        self._id = b"fake-transaction"

    def set(self, reference, document_data, merge=False):
        self._writes.append((reference.path, copy.deepcopy(document_data), merge))

    def _commit(self):
        for path, document_data, merge in self._writes:
            self._client._set(path, document_data, merge=merge)
        self._writes.clear()

    def _rollback(self):
        self._writes.clear()


class FakeFirestoreClient:
    def __init__(self):
        self._documents = {}

    def collection(self, collection_id):
        return FakeCollectionReference(self, collection_id)

    def document(self, document_path):
        return FakeDocumentReference(self, document_path)

    def transaction(self):
        return FakeTransaction(self)

    def _set(self, path, document_data, merge=False):
        if merge and path in self._documents:
            merged = copy.deepcopy(self._documents[path])
            merged.update(copy.deepcopy(document_data))
            self._documents[path] = merged
        else:
            self._documents[path] = copy.deepcopy(document_data)


def make_project(project_id="demo-api-staging", *, created_at=None):
    created_at = created_at or datetime(2026, 8, 12, 9, 30, 0)
    return Project(
        id=project_id,
        namespace=project_id,
        service_name="demo-api",
        environment="staging",
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


def make_audit_log(log_id, created_at):
    return AuditLog(
        id=log_id,
        project_id="demo-api-staging",
        action="PROJECT_RUNNING",
        status="SUCCESS",
        message=f"audit {log_id}",
        created_at=created_at,
    )


class FirestoreSettingsTests(unittest.TestCase):
    @patch("google.cloud.firestore.Client")
    def test_testing_memory_settings_do_not_construct_google_client(self, client):
        with patch.dict(
            "os.environ",
            {"APP_ENV": "testing", "REPOSITORY_BACKEND": "memory"},
            clear=True,
        ):
            settings = Settings(_env_file=None)

        self.assertEqual(settings.app_env, "testing")
        self.assertEqual(settings.repository_backend, "memory")
        self.assertEqual(settings.firestore_project_id, "")
        self.assertEqual(settings.firestore_database, "(default)")
        client.assert_not_called()


class FirestoreProjectRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeFirestoreClient()
        self.repository = FirestoreProjectRepository(
            client=self.client,
            max_active_projects=3,
        )

    def active_count(self):
        snapshot = self.client.document("system/demoCapacity").get()
        return snapshot.get("active_count") if snapshot.exists else 0

    def test_project_round_trip_preserves_status_and_utc_timestamps(self):
        project = make_project()

        saved = self.repository.save_project(project)
        loaded = self.repository.get_project(project.id)

        self.assertEqual(saved, project)
        self.assertEqual(loaded, project)
        stored = self.client.document(f"projects/{project.id}").get().to_dict()
        self.assertEqual(stored["status"], "RUNNING")
        self.assertEqual(stored["created_at"].tzinfo, UTC)
        self.assertEqual(stored["updated_at"].tzinfo, UTC)
        self.assertEqual(self.repository.list_projects(), [project])

    def test_claim_transaction_rejects_duplicate_document(self):
        project = make_project()
        self.repository.claim_capacity_and_create(project)

        with self.assertRaises(ProjectAlreadyExists):
            self.repository.claim_capacity_and_create(project)

        self.assertEqual(self.active_count(), 1)

    def test_claim_transaction_rejects_fourth_active_project(self):
        self.client.document("system/demoCapacity").set(
            {"active_count": 3, "max_active_projects": 3}
        )
        project = make_project("demo-four-staging")

        with self.assertRaises(DemoCapacityExceeded):
            self.repository.claim_capacity_and_create(project)

        self.assertEqual(self.active_count(), 3)
        self.assertFalse(self.client.document(f"projects/{project.id}").get().exists)

    def test_release_transaction_decrements_only_when_claimed(self):
        project = make_project()
        self.repository.claim_capacity_and_create(project)
        self.assertEqual(self.active_count(), 1)

        first_release = self.repository.release_capacity(project.id)
        second_release = self.repository.release_capacity(project.id)

        self.assertFalse(first_release.capacity_claimed)
        self.assertFalse(second_release.capacity_claimed)
        self.assertEqual(self.active_count(), 0)

    def test_release_transaction_rejects_unknown_project(self):
        with self.assertRaises(ProjectNotFound):
            self.repository.release_capacity("missing-project")

        self.assertEqual(self.active_count(), 0)

    def test_audit_logs_are_ordered_by_created_at_then_id(self):
        same_time = datetime(2026, 8, 12, 10, 0, 0)
        later_time = datetime(2026, 8, 12, 10, 0, 1)
        for log in (
            make_audit_log("b", same_time),
            make_audit_log("a", same_time),
            make_audit_log("later", later_time),
        ):
            self.repository.append_audit_log(log)

        logs = self.repository.list_audit_logs("demo-api-staging")

        self.assertEqual([log.id for log in logs], ["a", "b", "later"])
        self.assertTrue(all(log.created_at.tzinfo is None for log in logs))

    def test_health_check_reports_an_healthy_repository(self):
        self.assertEqual(self.repository.health_check(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
