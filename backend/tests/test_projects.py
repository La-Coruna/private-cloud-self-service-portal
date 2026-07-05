import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from kubernetes.client import ApiException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.k8s_client import create_namespace
from app.models import Project, ProjectStatus
from app.routers.projects import create_project, get_project, list_projects
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

    @patch("app.routers.projects.create_namespace")
    def test_create_project_persists_request_and_marks_running(
        self,
        mock_create_namespace: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-staging",
        }

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
        mock_create_namespace.assert_called_once_with(
            "demo-api-staging",
            project.id,
            "demo-api",
            "staging",
        )

        with self.SessionLocal() as db:
            saved_project = db.get(Project, project.id)
            self.assertIsNotNone(saved_project)
            self.assertEqual(saved_project.status, ProjectStatus.RUNNING)

    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_namespace_creation_fails(
        self,
        mock_create_namespace: MagicMock,
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

    @patch("app.routers.projects.create_namespace")
    def test_create_project_rejects_duplicate_namespace(
        self,
        mock_create_namespace: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
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

    @patch("app.routers.projects.create_namespace")
    def test_list_and_get_project_return_saved_projects(
        self,
        mock_create_namespace: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "already_exists",
            "namespace": "demo-api-prod",
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


class KubernetesNamespaceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
