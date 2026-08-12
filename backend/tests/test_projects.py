from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import (
    get_platform_status_service,
    get_project_service,
    get_repository,
)
from app.domain import AuditLog, PlatformAvailability, Project, ProjectStatus
from app.main import app
from app.repositories import InMemoryProjectRepository
from app.services import ProjectService


GKE_ERROR = {
    "error": {
        "code": "GKE_UNAVAILABLE",
        "message": "GKE 상태를 일시적으로 확인할 수 없습니다.",
        "detail": "Kubernetes API connection failed",
    }
}


def make_project(project_id: str = "demo-api-staging") -> Project:
    created_at = datetime(2026, 8, 12, 9, 30, 0)
    return Project(
        id=project_id,
        namespace=project_id,
        service_name="api",
        environment="staging",
        image="nginx:1.27",
        replicas=1,
        cpu_request="100m",
        cpu_limit="500m",
        memory_request="128Mi",
        memory_limit="512Mi",
        expose_external=False,
        ingress_host=None,
        status=ProjectStatus.RUNNING,
        error_message=None,
        capacity_claimed=True,
        created_at=created_at,
        updated_at=created_at,
    )


def make_platform_status(
    status: PlatformAvailability,
    *,
    message: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        message=message,
        creation_allowed=status == PlatformAvailability.AVAILABLE,
        checked_at=datetime(2026, 8, 12, 10, 0, 0),
    )


class ProjectApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryProjectRepository(max_active_projects=3)
        self.repository.save_project(make_project())
        self.kubernetes = MagicMock()
        self.platform_status = MagicMock()
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.UNAVAILABLE,
            message="Kubernetes API connection failed",
        )
        self.project_service = ProjectService(
            repository=self.repository,
            kubernetes=self.kubernetes,
            platform_status=self.platform_status,
            settings=Settings(app_env="testing", repository_backend="memory"),
        )
        app.dependency_overrides[get_repository] = lambda: self.repository
        app.dependency_overrides[get_project_service] = lambda: self.project_service
        app.dependency_overrides[get_platform_status_service] = (
            lambda: self.platform_status
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()

    def test_list_projects_returns_firestore_data_while_gke_is_unavailable(self) -> None:
        response = self.client.get("/api/projects")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]["id"], "demo-api-staging")
        self.assertIsInstance(response.json()[0]["id"], str)
        self.assertEqual(response.json()[0]["namespace"], "demo-api-staging")

    def test_get_project_returns_firestore_data_while_gke_is_unavailable(self) -> None:
        response = self.client.get("/api/projects/demo-api-staging")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], "demo-api-staging")
        self.assertEqual(response.json()["status"], "RUNNING")
        self.platform_status.get_status.assert_not_called()
        self.assertEqual(self.kubernetes.mock_calls, [])

    def test_create_project_returns_gke_unavailable_contract(self) -> None:
        response = self.client.post(
            "/api/projects",
            json={
                "service_name": "worker",
                "environment": "dev",
                "image": "nginx:1.27",
            },
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), GKE_ERROR)

    def test_pod_read_returns_gke_unavailable_contract(self) -> None:
        response = self.client.get("/api/projects/demo-api-staging/pods")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), GKE_ERROR)

    def test_pod_read_uses_service_gateway_with_string_namespace_id(self) -> None:
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.AVAILABLE,
            message="Platform has 1 Ready schedulable node(s)",
        )
        self.kubernetes.list_project_pods.return_value = [
            {
                "name": "api-abc",
                "namespace": "demo-api-staging",
                "phase": "Running",
                "pod_ip": "10.0.0.2",
                "node_name": "spot-node-1",
                "start_time": "2026-08-12T09:30:00",
                "containers": [
                    {
                        "name": "api",
                        "image": "nginx:1.27",
                        "ready": True,
                        "restart_count": 0,
                        "state": "running",
                        "reason": None,
                        "message": None,
                    }
                ],
            }
        ]

        response = self.client.get("/api/projects/demo-api-staging/pods")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["name"], "api-abc")
        self.kubernetes.list_project_pods.assert_called_once_with(
            namespace="demo-api-staging",
            project_id="demo-api-staging",
        )

    def test_event_read_uses_service_gateway_and_requested_limit(self) -> None:
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.AVAILABLE,
            message="Platform has 1 Ready schedulable node(s)",
        )
        self.kubernetes.list_project_events.return_value = []

        response = self.client.get(
            "/api/projects/demo-api-staging/events?limit=20"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        self.kubernetes.list_project_events.assert_called_once_with(
            namespace="demo-api-staging",
            project_id="demo-api-staging",
            service_name="api",
            limit=20,
        )

    def test_platform_status_exposes_recovering_state(self) -> None:
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.RECOVERING,
            message="Platform is reachable but has no Ready schedulable nodes",
        )

        response = self.client.get("/api/platform-status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "RECOVERING")
        self.assertFalse(response.json()["creation_allowed"])
        self.assertEqual(
            response.json()["message"],
            "Platform is reachable but has no Ready schedulable nodes",
        )
        self.assertEqual(response.json()["checked_at"], "2026-08-12T10:00:00")

    def test_health_is_200_with_healthy_firestore_and_unavailable_gke(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(
            response.json()["dependencies"]["firestore"],
            {"status": "ok"},
        )
        self.assertEqual(
            response.json()["dependencies"]["gke"]["status"],
            "UNAVAILABLE",
        )
        self.assertFalse(
            response.json()["dependencies"]["gke"]["creation_allowed"]
        )

    def test_health_reports_gke_independently_when_firestore_is_unhealthy(self) -> None:
        self.repository.health_check = MagicMock(
            side_effect=TimeoutError("Firestore read timed out")
        )

        response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["dependencies"]["firestore"]["status"],
            "error",
        )
        self.assertEqual(
            response.json()["dependencies"]["gke"]["status"], "UNAVAILABLE"
        )

    def test_audit_log_response_keeps_string_log_and_project_ids(self) -> None:
        self.repository.append_audit_log(
            AuditLog(
                id="log-1",
                project_id="demo-api-staging",
                action="PROJECT_RUNNING",
                status="SUCCESS",
                message="Project provisioning completed",
                created_at=datetime(2026, 8, 12, 9, 31, 0),
            )
        )

        response = self.client.get(
            "/api/projects/demo%2Dapi%2Dstaging/audit-logs"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["id"], "log-1")
        self.assertIsInstance(response.json()[0]["id"], str)
        self.assertEqual(response.json()[0]["project_id"], "demo-api-staging")
        self.assertIsInstance(response.json()[0]["project_id"], str)

    def test_missing_project_maps_to_404(self) -> None:
        response = self.client.get("/api/projects/missing-dev")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Project not found: missing-dev"})

    def test_duplicate_namespace_maps_to_409(self) -> None:
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.AVAILABLE,
            message="Platform has 1 Ready schedulable node(s)",
        )

        response = self.client.post(
            "/api/projects",
            json={
                "service_name": "demo-api",
                "environment": "staging",
                "image": "nginx:1.27",
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json(),
            {"detail": "Project already exists: demo-api-staging"},
        )

    def test_capacity_limit_maps_to_409(self) -> None:
        self.platform_status.get_status.return_value = make_platform_status(
            PlatformAvailability.AVAILABLE,
            message="Platform has 1 Ready schedulable node(s)",
        )
        limited_repository = InMemoryProjectRepository(max_active_projects=0)
        limited_service = ProjectService(
            repository=limited_repository,
            kubernetes=self.kubernetes,
            platform_status=self.platform_status,
            settings=Settings(app_env="testing", repository_backend="memory"),
        )
        app.dependency_overrides[get_project_service] = lambda: limited_service

        response = self.client.post(
            "/api/projects",
            json={
                "service_name": "worker",
                "environment": "dev",
                "image": "nginx:1.27",
            },
        )

        self.assertEqual(response.status_code, 409)

    def test_invalid_namespace_path_is_rejected_by_fastapi(self) -> None:
        response = self.client.get("/api/projects/INVALID_NAMESPACE")

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
