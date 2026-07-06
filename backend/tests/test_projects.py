import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from kubernetes.client import ApiException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.k8s_client import (
    build_selector_labels,
    create_deployment,
    create_namespace,
    create_service,
    list_project_pods,
)
from app.models import Project, ProjectStatus
from app.routers.projects import (
    create_project,
    get_project,
    get_project_pods,
    list_projects,
)
from app.schemas import ProjectCreateRequest


class ProjectSchemaTests(unittest.TestCase):
    def test_project_create_request_rejects_invalid_service_name(self) -> None:
        with self.assertRaises(ValidationError):
            ProjectCreateRequest(
                service_name="Demo_API",
                environment="dev",
                image="nginx:latest",
            )

    def test_project_create_request_applies_resource_defaults(self) -> None:
        request = ProjectCreateRequest(
            service_name="demo-api",
            environment="staging",
            image="nginx:latest",
        )

        self.assertEqual(request.replicas, 1)
        self.assertEqual(request.cpu_request, "100m")
        self.assertEqual(request.cpu_limit, "500m")
        self.assertEqual(request.memory_request, "128Mi")
        self.assertEqual(request.memory_limit, "512Mi")
        self.assertFalse(request.expose_external)


class ProjectApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_persists_request_and_marks_running(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        call_order = []

        def namespace_result(*args):
            call_order.append("namespace")
            return {"status": "created", "namespace": "demo-api-staging"}

        def deployment_result(*args, **kwargs):
            call_order.append("deployment")
            return {
                "status": "created",
                "resource": "deployment",
                "name": "demo-api",
            }

        def service_result(*args, **kwargs):
            call_order.append("service")
            return {
                "status": "created",
                "resource": "service",
                "name": "demo-api-svc",
            }

        mock_create_namespace.side_effect = namespace_result
        mock_create_deployment.side_effect = deployment_result
        mock_create_service.side_effect = service_result

        project = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="staging",
                image="nginx:latest",
            ),
            db=self.db,
        )

        self.assertEqual(project.service_name, "demo-api")
        self.assertEqual(project.environment, "staging")
        self.assertEqual(project.namespace, "demo-api-staging")
        self.assertEqual(project.status, ProjectStatus.RUNNING)
        self.assertIsNone(project.error_message)
        self.assertEqual(call_order, ["namespace", "deployment", "service"])
        mock_create_namespace.assert_called_once_with(
            "demo-api-staging",
            project.id,
            "demo-api",
            "staging",
        )
        mock_create_deployment.assert_called_once_with(
            namespace="demo-api-staging",
            project_id=project.id,
            service_name="demo-api",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
        )
        mock_create_service.assert_called_once_with(
            namespace="demo-api-staging",
            project_id=project.id,
            service_name="demo-api",
            environment="staging",
        )

        with self.SessionLocal() as db:
            saved_project = db.get(Project, project.id)
            self.assertIsNotNone(saved_project)
            self.assertEqual(saved_project.status, ProjectStatus.RUNNING)

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_namespace_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "error",
            "message": "forbidden",
            "detail": "policy denied",
        }

        project = create_project(
            request=ProjectCreateRequest(
                service_name="blocked-api",
                environment="dev",
                image="nginx:latest",
            ),
            db=self.db,
        )

        self.assertEqual(project.status, ProjectStatus.FAILED)
        self.assertIn("forbidden", project.error_message)
        self.assertIn("policy denied", project.error_message)
        mock_create_deployment.assert_not_called()
        mock_create_service.assert_not_called()

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_deployment_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
        }
        mock_create_deployment.return_value = {
            "status": "error",
            "resource": "deployment",
            "message": "deployment denied",
            "detail": "quota exceeded",
        }

        project = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="dev",
                image="nginx:latest",
            ),
            db=self.db,
        )

        self.assertEqual(project.status, ProjectStatus.FAILED)
        self.assertIn("deployment", project.error_message)
        self.assertIn("deployment denied", project.error_message)
        self.assertIn("quota exceeded", project.error_message)
        mock_create_service.assert_not_called()

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_service_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-prod",
        }
        mock_create_deployment.return_value = {
            "status": "created",
            "resource": "deployment",
            "name": "demo-api",
        }
        mock_create_service.return_value = {
            "status": "error",
            "resource": "service",
            "message": "service denied",
            "detail": "invalid selector",
        }

        project = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="prod",
                image="nginx:latest",
            ),
            db=self.db,
        )

        self.assertEqual(project.status, ProjectStatus.FAILED)
        self.assertIn("service", project.error_message)
        self.assertIn("service denied", project.error_message)
        self.assertIn("invalid selector", project.error_message)

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_rejects_duplicate_namespace(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
        }
        mock_create_deployment.return_value = {
            "status": "created",
            "resource": "deployment",
            "name": "demo-api",
        }
        mock_create_service.return_value = {
            "status": "created",
            "resource": "service",
            "name": "demo-api-svc",
        }
        payload = ProjectCreateRequest(
            service_name="demo-api",
            environment="dev",
            image="nginx:latest",
        )

        create_project(request=payload, db=self.db)
        with self.assertRaises(HTTPException) as exc:
            create_project(request=payload, db=self.db)

        self.assertEqual(exc.exception.status_code, 409)
        self.assertEqual(
            exc.exception.detail,
            "Namespace already requested: demo-api-dev",
        )

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_namespace")
    def test_list_and_get_project_return_saved_projects(
        self,
        mock_create_namespace: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "already_exists",
            "namespace": "demo-api-prod",
        }
        mock_create_deployment.return_value = {
            "status": "already_exists",
            "resource": "deployment",
            "name": "demo-api",
        }
        mock_create_service.return_value = {
            "status": "already_exists",
            "resource": "service",
            "name": "demo-api-svc",
        }

        created = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="prod",
                image="nginx:latest",
                replicas=2,
            ),
            db=self.db,
        )

        projects = list_projects(db=self.db)
        detail = get_project(project_id=created.id, db=self.db)

        self.assertEqual(projects[0].id, created.id)
        self.assertEqual(detail.replicas, 2)

        with self.assertRaises(HTTPException) as exc:
            get_project(project_id=999, db=self.db)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Project not found: 999")

    @patch("app.routers.projects.list_project_pods")
    def test_get_project_pods_returns_kubernetes_pod_statuses(
        self,
        mock_list_project_pods: MagicMock,
    ) -> None:
        project = Project(
            service_name="demo-api",
            environment="dev",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="demo-api-dev",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        mock_list_project_pods.return_value = [
            {
                "name": "demo-api-abc",
                "namespace": "demo-api-dev",
                "phase": "Running",
                "pod_ip": "10.244.0.5",
                "node_name": "portal-dev-control-plane",
                "start_time": "2026-07-05T07:00:00+00:00",
                "containers": [
                    {
                        "name": "demo-api",
                        "image": "nginx:latest",
                        "ready": True,
                        "restart_count": 0,
                        "state": "running",
                        "reason": None,
                        "message": None,
                    }
                ],
            }
        ]

        pods = get_project_pods(project_id=project.id, db=self.db)

        self.assertEqual(pods, mock_list_project_pods.return_value)
        mock_list_project_pods.assert_called_once_with(
            namespace="demo-api-dev",
            project_id=project.id,
        )

    def test_get_project_pods_returns_404_for_missing_project(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            get_project_pods(project_id=999, db=self.db)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Project not found: 999")

    @patch("app.routers.projects.list_project_pods")
    def test_get_project_pods_translates_kubernetes_errors(
        self,
        mock_list_project_pods: MagicMock,
    ) -> None:
        project = Project(
            service_name="demo-api",
            environment="dev",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="demo-api-dev",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        mock_list_project_pods.side_effect = RuntimeError("pods unavailable")

        with self.assertRaises(HTTPException) as exc:
            get_project_pods(project_id=project.id, db=self.db)

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "pods unavailable")


class KubernetesNamespaceTests(unittest.TestCase):
    def test_build_selector_labels_includes_service_name_and_project_id(self) -> None:
        self.assertEqual(
            build_selector_labels(7, "demo-api"),
            {
                "app.kubernetes.io/name": "demo-api",
                "platform.io/project-id": "7",
            },
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_namespace_sends_expected_metadata(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = create_namespace("demo-api-staging", 7, "demo-api", "staging")

        self.assertEqual(result, {"status": "created", "namespace": "demo-api-staging"})
        mock_load_kube_config.assert_called_once()
        namespace = api.create_namespace.call_args.args[0]
        self.assertEqual(namespace.metadata.name, "demo-api-staging")
        self.assertEqual(
            namespace.metadata.labels,
            {
                "app.kubernetes.io/managed-by": "self-service-portal",
                "app.kubernetes.io/name": "demo-api",
                "platform.io/environment": "staging",
                "platform.io/project-id": "7",
            },
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_namespace_reports_already_exists_for_conflict(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.create_namespace.side_effect = ApiException(status=409, reason="Conflict")

        result = create_namespace("demo-api-dev", 3, "demo-api", "dev")

        self.assertEqual(result, {"status": "already_exists", "namespace": "demo-api-dev"})

    @patch("app.k8s_client.client.AppsV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_deployment_sends_expected_workload_spec(
        self,
        mock_load_kube_config: MagicMock,
        mock_apps_v1_api: MagicMock,
    ) -> None:
        api = mock_apps_v1_api.return_value

        result = create_deployment(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            environment="staging",
            image="nginx:latest",
            replicas=2,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
        )

        self.assertEqual(
            result,
            {"status": "created", "resource": "deployment", "name": "demo-api"},
        )
        deployment = api.create_namespaced_deployment.call_args.kwargs["body"]
        self.assertEqual(api.create_namespaced_deployment.call_args.kwargs["namespace"], "demo-api-staging")
        self.assertEqual(deployment.metadata.name, "demo-api")
        self.assertEqual(deployment.spec.replicas, 2)
        self.assertEqual(
            deployment.spec.selector.match_labels,
            {
                "app.kubernetes.io/name": "demo-api",
                "platform.io/project-id": "7",
            },
        )
        self.assertEqual(
            deployment.spec.template.metadata.labels,
            deployment.spec.selector.match_labels,
        )
        container = deployment.spec.template.spec.containers[0]
        self.assertEqual(container.name, "demo-api")
        self.assertEqual(container.image, "nginx:latest")
        self.assertEqual(container.ports[0].container_port, 80)
        self.assertEqual(container.resources.requests["cpu"], "100m")
        self.assertEqual(container.resources.limits["memory"], "512Mi")

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_service_sends_expected_cluster_ip_service(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = create_service(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            environment="staging",
        )

        self.assertEqual(
            result,
            {"status": "created", "resource": "service", "name": "demo-api-svc"},
        )
        service = api.create_namespaced_service.call_args.kwargs["body"]
        self.assertEqual(api.create_namespaced_service.call_args.kwargs["namespace"], "demo-api-staging")
        self.assertEqual(service.metadata.name, "demo-api-svc")
        self.assertEqual(service.spec.type, "ClusterIP")
        self.assertEqual(
            service.spec.selector,
            {
                "app.kubernetes.io/name": "demo-api",
                "platform.io/project-id": "7",
            },
        )
        self.assertEqual(service.spec.ports[0].name, "http")
        self.assertEqual(service.spec.ports[0].port, 80)
        self.assertEqual(service.spec.ports[0].target_port, 80)

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_pods_formats_container_statuses(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        running_state = MagicMock()
        running_state.running = object()
        running_state.waiting = None
        running_state.terminated = None
        waiting_state = MagicMock()
        waiting_state.running = None
        waiting_state.waiting.reason = "ImagePullBackOff"
        waiting_state.waiting.message = "Back-off pulling image"
        waiting_state.terminated = None
        pod = MagicMock()
        pod.metadata.name = "demo-api-abc"
        pod.metadata.namespace = "demo-api-staging"
        pod.status.phase = "Pending"
        pod.status.pod_ip = None
        pod.status.host_ip = "10.0.0.1"
        pod.spec.node_name = "portal-dev-control-plane"
        pod.status.start_time.isoformat.return_value = "2026-07-05T07:00:00+00:00"
        running_container = MagicMock()
        running_container.name = "demo-api"
        running_container.image = "nginx:latest"
        running_container.ready = True
        running_container.restart_count = 0
        running_container.state = running_state
        waiting_container = MagicMock()
        waiting_container.name = "sidecar"
        waiting_container.image = "missing:latest"
        waiting_container.ready = False
        waiting_container.restart_count = 3
        waiting_container.state = waiting_state
        pod.status.container_statuses = [running_container, waiting_container]
        api.list_namespaced_pod.return_value.items = [pod]

        pods = list_project_pods(namespace="demo-api-staging", project_id=7)

        api.list_namespaced_pod.assert_called_once_with(
            namespace="demo-api-staging",
            label_selector="platform.io/project-id=7",
        )
        self.assertEqual(pods[0]["name"], "demo-api-abc")
        self.assertEqual(pods[0]["phase"], "Pending")
        self.assertEqual(pods[0]["containers"][0]["state"], "running")
        self.assertEqual(pods[0]["containers"][1]["state"], "waiting")
        self.assertEqual(pods[0]["containers"][1]["reason"], "ImagePullBackOff")


if __name__ == "__main__":
    unittest.main()
