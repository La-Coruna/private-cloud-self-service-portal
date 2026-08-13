from types import SimpleNamespace
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import MagicMock

from app.config import Settings
from app.domain import PlatformAvailability, Project, ProjectStatus
from app.repositories.memory import InMemoryProjectRepository
from app.schemas import ProjectCreateRequest
from app.services.project_service import (
    InvalidLifecycleOperation,
    ProjectService,
    derive_project_status,
)


def make_request(*, expose_external: bool = False) -> ProjectCreateRequest:
    return ProjectCreateRequest(
        service_name="demo-api",
        environment="staging",
        image="nginx:1.27",
        replicas=2,
        cpu_request="250m",
        cpu_limit="1",
        memory_request="256Mi",
        memory_limit="1Gi",
        expose_external=expose_external,
    )


def successful_result(resource: str, name: str) -> dict:
    return {"status": "created", "resource": resource, "name": name}


def deleted_result(resource: str, name: str) -> dict:
    return {"status": "deleted", "resource": resource, "name": name}


class ProjectServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryProjectRepository(max_active_projects=3)
        self.kubernetes = MagicMock()
        self.kubernetes.verify_project_resources.return_value = {"status": "verified"}
        self.platform_status = MagicMock()
        self.platform_status.get_status.return_value = SimpleNamespace(
            status=PlatformAvailability.AVAILABLE,
            message="GKE is available",
            creation_allowed=True,
        )
        self.settings = Settings(
            demo_mode=True,
            demo_namespace_prefix="demo-",
            ingress_base_domain="example.test",
        )
        self.service = ProjectService(
            repository=self.repository,
            kubernetes=self.kubernetes,
            platform_status=self.platform_status,
            settings=self.settings,
        )

    def _configure_successful_create(self, call_order: list[str]) -> None:
        self.kubernetes.create_namespace.side_effect = (
            lambda *args, **kwargs: call_order.append("namespace")
            or {"status": "created", "namespace": "demo-demo-api-staging"}
        )
        self.kubernetes.create_resource_quota.side_effect = (
            lambda *args, **kwargs: call_order.append("resourcequota")
            or successful_result("resourcequota", "portal-resource-quota")
        )
        self.kubernetes.create_deployment.side_effect = (
            lambda *args, **kwargs: call_order.append("deployment")
            or successful_result("deployment", "demo-api")
        )
        self.kubernetes.create_service.side_effect = (
            lambda *args, **kwargs: call_order.append("service")
            or successful_result("service", "demo-api-svc")
        )
        self.kubernetes.create_ingress.side_effect = (
            lambda *args, **kwargs: call_order.append("ingress")
            or successful_result("ingress", "demo-api-ingress")
        )

    def _create_running_project(self) -> Project:
        call_order: list[str] = []
        self._configure_successful_create(call_order)
        project = self.service.create_project(make_request())
        self.assertEqual(
            call_order,
            ["namespace", "resourcequota", "deployment", "service"],
        )
        return project

    def test_create_project_claims_capacity_and_creates_resources_in_order(self) -> None:
        call_order: list[str] = []
        self._configure_successful_create(call_order)

        project = self.service.create_project(make_request(expose_external=True))

        stored = self.repository.get_project(project.id)
        self.assertEqual(project.status, ProjectStatus.RUNNING)
        self.assertEqual(stored.status, ProjectStatus.RUNNING)
        self.assertTrue(project.capacity_claimed)
        self.assertTrue(stored.capacity_claimed)
        self.assertEqual(project.ingress_host, "demo-api-staging.example.test")
        self.assertEqual(
            call_order,
            ["namespace", "resourcequota", "deployment", "service", "ingress"],
        )
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            [
                "PROJECT_CREATE_REQUESTED",
                "PROJECT_PROVISIONING_STARTED",
                "NAMESPACE_CREATED",
                "RESOURCE_QUOTA_CREATED",
                "DEPLOYMENT_CREATED",
                "SERVICE_CREATED",
                "INGRESS_CREATED",
                "PROJECT_RUNNING",
            ],
        )

    def test_non_demo_mode_does_not_apply_demo_project_capacity_limit(self) -> None:
        repository = InMemoryProjectRepository(max_active_projects=None)
        service = ProjectService(
            repository=repository,
            kubernetes=self.kubernetes,
            platform_status=self.platform_status,
            settings=Settings(demo_mode=False, demo_max_projects=3),
        )
        self.kubernetes.create_namespace.return_value = {"status": "created"}
        self.kubernetes.create_resource_quota.return_value = successful_result(
            "resourcequota", "portal-resource-quota"
        )
        self.kubernetes.create_deployment.return_value = successful_result(
            "deployment", "api"
        )
        self.kubernetes.create_service.return_value = successful_result(
            "service", "api-svc"
        )

        projects = [
            service.create_project(
                ProjectCreateRequest(
                    service_name=f"api-{index}",
                    environment="staging",
                    image="nginx:1.27",
                )
            )
            for index in range(1, 5)
        ]

        self.assertEqual(len(projects), 4)
        self.assertEqual(repository.active_count, 4)
        self.assertTrue(all(project.capacity_claimed for project in projects))

    def test_deployment_failure_marks_failed_and_releases_capacity_once(self) -> None:
        call_order: list[str] = []
        self._configure_successful_create(call_order)
        self.kubernetes.create_deployment.side_effect = (
            lambda *args, **kwargs: call_order.append("deployment")
            or {
                "status": "error",
                "resource": "deployment",
                "message": "Forbidden",
                "detail": "service account lacks permission",
            }
        )
        release_capacity = MagicMock(wraps=self.repository.release_capacity)
        self.repository.release_capacity = release_capacity

        project = self.service.create_project(make_request())

        stored = self.repository.get_project(project.id)
        self.assertEqual(stored.status, ProjectStatus.FAILED)
        self.assertEqual(
            stored.error_message,
            "deployment: Forbidden: service account lacks permission",
        )
        self.assertFalse(stored.capacity_claimed)
        release_capacity.assert_called_once_with(project.id)
        self.assertEqual(call_order, ["namespace", "resourcequota", "deployment"])
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            [
                "PROJECT_CREATE_REQUESTED",
                "PROJECT_PROVISIONING_STARTED",
                "NAMESPACE_CREATED",
                "RESOURCE_QUOTA_CREATED",
                "DEPLOYMENT_CREATE_FAILED",
            ],
        )

    def test_delete_persists_deleting_before_reverse_order_calls_and_releases_capacity(self) -> None:
        project = self._create_running_project()
        observed_states: list[ProjectStatus] = []
        delete_order: list[str] = []

        def delete_result(resource: str, name: str) -> dict:
            observed_states.append(self.repository.get_project(project.id).status)
            delete_order.append(resource)
            return deleted_result(resource, name)

        self.kubernetes.delete_ingress.side_effect = (
            lambda *args, **kwargs: delete_result("ingress", "demo-api-ingress")
        )
        self.kubernetes.delete_service.side_effect = (
            lambda *args, **kwargs: delete_result("service", "demo-api-svc")
        )
        self.kubernetes.delete_deployment.side_effect = (
            lambda *args, **kwargs: delete_result("deployment", "demo-api")
        )
        self.kubernetes.delete_resource_quota.side_effect = (
            lambda *args, **kwargs: delete_result("resourcequota", "portal-resource-quota")
        )
        self.kubernetes.delete_namespace.side_effect = (
            lambda *args, **kwargs: delete_result("namespace", project.namespace)
        )
        release_capacity = MagicMock(wraps=self.repository.release_capacity)
        self.repository.release_capacity = release_capacity

        deleted = self.service.delete_project(project.id)

        stored = self.repository.get_project(project.id)
        self.assertEqual(observed_states, [ProjectStatus.DELETING] * 5)
        self.assertEqual(
            delete_order,
            ["ingress", "service", "deployment", "resourcequota", "namespace"],
        )
        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        self.assertEqual(stored.status, ProjectStatus.DELETED)
        self.assertFalse(stored.capacity_claimed)
        release_capacity.assert_not_called()
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            [
                "PROJECT_CREATE_REQUESTED",
                "PROJECT_PROVISIONING_STARTED",
                "NAMESPACE_CREATED",
                "RESOURCE_QUOTA_CREATED",
                "DEPLOYMENT_CREATED",
                "SERVICE_CREATED",
                "INGRESS_SKIPPED",
                "PROJECT_RUNNING",
                "PROJECT_DELETE_REQUESTED",
                "INGRESS_DELETED",
                "SERVICE_DELETED",
                "DEPLOYMENT_DELETED",
                "RESOURCE_QUOTA_DELETED",
                "NAMESPACE_DELETED",
                "PROJECT_DELETED",
            ],
        )

    def test_retry_resumes_requested_project_after_initial_status_save_failure(self) -> None:
        original_save = self.repository.save_project_if_version
        self.repository.save_project_if_version = MagicMock(
            side_effect=RuntimeError("transient Firestore write failure")
        )

        with self.assertRaisesRegex(RuntimeError, "transient Firestore write failure"):
            self.service.create_project(make_request())

        project_id = "demo-demo-api-staging"
        stranded = self.repository.get_project(project_id)
        self.assertEqual(stranded.status, ProjectStatus.REQUESTED)
        self.assertTrue(stranded.capacity_claimed)
        self.assertEqual(self.repository.active_count, 1)
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project_id)],
            ["PROJECT_CREATE_REQUESTED"],
        )
        self.assertEqual(self.kubernetes.mock_calls, [])

        self.repository.save_project_if_version = original_save
        call_order: list[str] = []
        self._configure_successful_create(call_order)

        retried = self.service.create_project(make_request())

        self.assertEqual(retried.status, ProjectStatus.RUNNING)
        self.assertEqual(self.repository.active_count, 1)
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project_id)].count(
                "PROJECT_CREATE_REQUESTED"
            ),
            1,
        )

    def test_concurrent_deletes_allow_only_one_kubernetes_deletion_owner(self) -> None:
        project = self._create_running_project()
        verification_barrier = Barrier(2)

        def verify_ownership(**kwargs) -> dict:
            verification_barrier.wait()
            return {"status": "verified"}

        self.kubernetes.verify_project_resources.side_effect = verify_ownership
        for method_name, result in (
            ("delete_ingress", deleted_result("ingress", "demo-api-ingress")),
            ("delete_service", deleted_result("service", "demo-api-svc")),
            ("delete_deployment", deleted_result("deployment", "demo-api")),
            (
                "delete_resource_quota",
                deleted_result("resourcequota", "portal-resource-quota"),
            ),
            ("delete_namespace", deleted_result("namespace", project.namespace)),
        ):
            getattr(self.kubernetes, method_name).return_value = result

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(self.service.delete_project, project.id)
                for _ in range(2)
            ]
            outcomes = []
            for future in futures:
                try:
                    outcomes.append(future.result())
                except InvalidLifecycleOperation as exc:
                    outcomes.append(exc)

        self.assertEqual(len(outcomes), 2)
        self.assertTrue(
            all(
                isinstance(outcome, (Project, InvalidLifecycleOperation))
                for outcome in outcomes
            )
        )
        self.assertEqual(self.kubernetes.delete_namespace.call_count, 1)
        self.assertEqual(self.repository.active_count, 0)
        self.assertEqual(
            self.repository.get_project(project.id).status,
            ProjectStatus.DELETED,
        )

    def test_stale_sync_cannot_restore_running_after_delete_completes(self) -> None:
        project = self._create_running_project()
        sync_read_platform = Event()
        allow_sync_to_save = Event()

        def delayed_pods(**kwargs) -> list[dict]:
            sync_read_platform.set()
            self.assertTrue(allow_sync_to_save.wait(timeout=5))
            return [
                {
                    "name": "demo-api-abc",
                    "phase": "Running",
                    "containers": [
                        {
                            "name": "demo-api",
                            "ready": True,
                            "state": "running",
                            "reason": None,
                            "message": None,
                        }
                    ],
                }
            ]

        self.kubernetes.list_project_pods.side_effect = delayed_pods
        self.kubernetes.list_project_events.return_value = []
        self.kubernetes.delete_ingress.return_value = deleted_result(
            "ingress", "demo-api-ingress"
        )
        self.kubernetes.delete_service.return_value = deleted_result(
            "service", "demo-api-svc"
        )
        self.kubernetes.delete_deployment.return_value = deleted_result(
            "deployment", "demo-api"
        )
        self.kubernetes.delete_resource_quota.return_value = deleted_result(
            "resourcequota", "portal-resource-quota"
        )
        self.kubernetes.delete_namespace.return_value = deleted_result(
            "namespace", project.namespace
        )

        with ThreadPoolExecutor(max_workers=1) as executor:
            syncing = executor.submit(self.service.sync_status, project.id)
            self.assertTrue(sync_read_platform.wait(timeout=5))
            deleted = self.service.delete_project(project.id)
            allow_sync_to_save.set()
            synced = syncing.result(timeout=5)

        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        self.assertEqual(synced.status, ProjectStatus.DELETED)
        self.assertEqual(self.repository.active_count, 0)
        self.assertEqual(
            self.repository.get_project(project.id).status,
            ProjectStatus.DELETED,
        )

    def test_partial_delete_failure_keeps_capacity_and_records_failure(self) -> None:
        project = self._create_running_project()
        self.kubernetes.delete_ingress.return_value = deleted_result(
            "ingress", "demo-api-ingress"
        )
        self.kubernetes.delete_service.return_value = {
            "status": "error",
            "resource": "service",
            "name": "demo-api-svc",
            "message": "Forbidden",
            "detail": "RBAC denied",
        }
        self.kubernetes.delete_deployment.return_value = deleted_result(
            "deployment", "demo-api"
        )
        self.kubernetes.delete_resource_quota.return_value = deleted_result(
            "resourcequota", "portal-resource-quota"
        )
        self.kubernetes.delete_namespace.return_value = deleted_result(
            "namespace", project.namespace
        )
        release_capacity = MagicMock(wraps=self.repository.release_capacity)
        self.repository.release_capacity = release_capacity

        failed = self.service.delete_project(project.id)

        stored = self.repository.get_project(project.id)
        self.assertEqual(failed.status, ProjectStatus.FAILED)
        self.assertEqual(stored.status, ProjectStatus.FAILED)
        self.assertTrue(stored.capacity_claimed)
        self.assertEqual(
            stored.error_message,
            "service/demo-api-svc: Forbidden - RBAC denied",
        )
        release_capacity.assert_not_called()
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            [
                "PROJECT_CREATE_REQUESTED",
                "PROJECT_PROVISIONING_STARTED",
                "NAMESPACE_CREATED",
                "RESOURCE_QUOTA_CREATED",
                "DEPLOYMENT_CREATED",
                "SERVICE_CREATED",
                "INGRESS_SKIPPED",
                "PROJECT_RUNNING",
                "PROJECT_DELETE_REQUESTED",
                "INGRESS_DELETED",
                "SERVICE_DELETED",
                "DEPLOYMENT_DELETED",
                "RESOURCE_QUOTA_DELETED",
                "NAMESPACE_DELETED",
                "PROJECT_DELETE_FAILED",
            ],
        )

    def test_delete_of_deleted_project_is_idempotent_without_kubernetes_calls(self) -> None:
        project = Project.new(make_request(), "demo-demo-api-staging")
        project.status = ProjectStatus.DELETED
        self.repository.save_project(project)

        deleted = self.service.delete_project(project.id)

        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        self.assertEqual(self.kubernetes.mock_calls, [])
        self.platform_status.get_status.assert_not_called()
        self.assertEqual(self.repository.list_audit_logs(project.id), [])

    def test_sync_ready_pods_marks_project_running(self) -> None:
        project = Project.new(make_request(), "demo-demo-api-staging")
        project.status = ProjectStatus.PROVISIONING
        self.repository.save_project(project)
        self.kubernetes.list_project_pods.return_value = [
            {
                "name": "demo-api-abc",
                "phase": "Running",
                "containers": [
                    {
                        "name": "demo-api",
                        "ready": True,
                        "state": "running",
                        "reason": None,
                        "message": None,
                    }
                ],
            }
        ]
        self.kubernetes.list_project_events.return_value = []

        synced = self.service.sync_status(project.id)

        self.assertEqual(synced.status, ProjectStatus.RUNNING)
        self.assertIsNone(synced.error_message)
        self.assertEqual(
            self.repository.get_project(project.id).status,
            ProjectStatus.RUNNING,
        )
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            ["PROJECT_STATUS_SYNCED"],
        )

    def test_sync_deleted_project_is_idempotent_without_kubernetes_calls(self) -> None:
        project = Project.new(make_request(), "demo-demo-api-staging")
        project.status = ProjectStatus.DELETED
        self.repository.save_project(project)

        synced = self.service.sync_status(project.id)

        self.assertEqual(synced.status, ProjectStatus.DELETED)
        self.assertEqual(
            self.repository.get_project(project.id).status,
            ProjectStatus.DELETED,
        )
        self.assertEqual(self.kubernetes.mock_calls, [])
        self.platform_status.get_status.assert_not_called()
        self.assertEqual(
            [log.action for log in self.repository.list_audit_logs(project.id)],
            ["PROJECT_STATUS_SYNC_SKIPPED"],
        )

    def test_status_derivation_reports_waiting_container_failure_details(self) -> None:
        pods = [
            {
                "name": "demo-api-abc",
                "phase": "Pending",
                "containers": [
                    {
                        "name": "demo-api",
                        "ready": False,
                        "state": "waiting",
                        "reason": "ImagePullBackOff",
                        "message": "Back-off pulling image",
                    }
                ],
            }
        ]
        events = [{"reason": "Failed", "message": "Failed to pull image"}]

        status, detail = derive_project_status(pods, events)

        self.assertEqual(status, ProjectStatus.FAILED)
        self.assertEqual(
            detail,
            "demo-api-abc/demo-api waiting: ImagePullBackOff - Back-off pulling image"
            " | Latest event Failed: Failed to pull image",
        )


if __name__ == "__main__":
    unittest.main()
