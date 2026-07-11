from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from kubernetes.client import ApiException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit import create_audit_log
from app.db import Base
from app.k8s_client import (
    build_ingress_host,
    build_selector_labels,
    create_deployment,
    create_ingress,
    create_namespace,
    create_resource_quota,
    create_service,
    delete_deployment,
    delete_ingress,
    delete_namespace,
    delete_project_resources,
    delete_resource_quota,
    delete_service,
    list_project_events,
    list_project_pods,
)
from app.models import AuditLog, Project, ProjectStatus
from app.routers.projects import (
    create_project,
    delete_project,
    get_project,
    get_project_audit_logs,
    get_project_events,
    get_project_pods,
    list_projects,
)
from app.schemas import ProjectCreateRequest


class AuditLogHelperTests(unittest.TestCase):
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

    def test_create_audit_log_persists_project_lifecycle_event(self) -> None:
        project = Project(
            service_name="audit-demo",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="audit-demo-staging",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        log = create_audit_log(
            db=self.db,
            project_id=project.id,
            action="PROJECT_RUNNING",
            status="SUCCESS",
            message="Project provisioning completed",
        )

        self.assertIsNotNone(log.id)
        self.assertEqual(log.project_id, project.id)
        self.assertEqual(log.action, "PROJECT_RUNNING")
        self.assertEqual(log.status, "SUCCESS")
        self.assertEqual(log.message, "Project provisioning completed")
        saved_logs = self.db.query(AuditLog).filter(AuditLog.project_id == project.id).all()
        self.assertEqual(len(saved_logs), 1)


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

    def test_project_response_includes_ingress_host(self) -> None:
        from app.schemas import ProjectResponse

        self.assertIn("ingress_host", ProjectResponse.model_fields)


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
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_persists_request_and_marks_running(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        call_order = []

        def namespace_result(*args):
            call_order.append("namespace")
            return {"status": "created", "namespace": "demo-api-staging"}

        def quota_result(*args, **kwargs):
            call_order.append("resourcequota")
            return {
                "status": "created",
                "resource": "resourcequota",
                "name": "portal-resource-quota",
            }

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
        mock_create_resource_quota.side_effect = quota_result
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
        self.assertIsNone(getattr(project, "ingress_host", None))
        self.assertEqual(project.status, ProjectStatus.RUNNING)
        self.assertIsNone(project.error_message)
        self.assertEqual(call_order, ["namespace", "resourcequota", "deployment", "service"])
        mock_create_namespace.assert_called_once_with(
            "demo-api-staging",
            project.id,
            "demo-api",
            "staging",
        )
        mock_create_resource_quota.assert_called_once_with(
            namespace="demo-api-staging",
            project_id=project.id,
            service_name="demo-api",
            environment="staging",
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
            audit_actions = [
                log.action
                for log in db.query(AuditLog)
                .filter(AuditLog.project_id == project.id)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
                .all()
            ]
            self.assertEqual(
                audit_actions,
                [
                    "PROJECT_CREATE_REQUESTED",
                    "PROJECT_PROVISIONING_STARTED",
                    "NAMESPACE_CREATED",
                    "RESOURCE_QUOTA_CREATED",
                    "DEPLOYMENT_CREATED",
                    "SERVICE_CREATED",
                    "INGRESS_SKIPPED",
                    "PROJECT_RUNNING",
                ],
            )

    @patch("app.routers.projects.create_ingress")
    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_creates_ingress_for_external_project(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
        mock_create_ingress: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-staging",
        }
        mock_create_resource_quota.return_value = {
            "status": "created",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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
        mock_create_ingress.return_value = {
            "status": "created",
            "resource": "ingress",
            "name": "demo-api-ingress",
        }

        project = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="staging",
                image="nginx:latest",
                expose_external=True,
            ),
            db=self.db,
        )

        self.assertEqual(project.status, ProjectStatus.RUNNING)
        self.assertEqual(project.ingress_host, "demo-api-staging.localtest.me")
        mock_create_ingress.assert_called_once_with(
            namespace="demo-api-staging",
            project_id=project.id,
            service_name="demo-api",
            environment="staging",
            host="demo-api-staging.localtest.me",
        )
        audit_actions = [
            log.action
            for log in self.db.query(AuditLog)
            .filter(AuditLog.project_id == project.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .all()
        ]
        self.assertIn("INGRESS_CREATED", audit_actions)
        self.assertNotIn("INGRESS_SKIPPED", audit_actions)

    @patch("app.routers.projects.create_ingress")
    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_ingress_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
        mock_create_ingress: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-staging",
        }
        mock_create_resource_quota.return_value = {
            "status": "created",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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
        mock_create_ingress.return_value = {
            "status": "error",
            "resource": "ingress",
            "message": "ingress denied",
            "detail": "host policy denied",
        }

        project = create_project(
            request=ProjectCreateRequest(
                service_name="demo-api",
                environment="staging",
                image="nginx:latest",
                expose_external=True,
            ),
            db=self.db,
        )

        self.assertEqual(project.status, ProjectStatus.FAILED)
        self.assertIn("ingress", project.error_message)
        self.assertIn("host policy denied", project.error_message)
        audit_actions = [
            log.action
            for log in self.db.query(AuditLog)
            .filter(AuditLog.project_id == project.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .all()
        ]
        self.assertEqual(audit_actions[-1], "INGRESS_CREATE_FAILED")

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_namespace_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
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
        mock_create_resource_quota.assert_not_called()
        mock_create_deployment.assert_not_called()
        mock_create_service.assert_not_called()

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_resource_quota_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
        }
        mock_create_resource_quota.return_value = {
            "status": "error",
            "resource": "resourcequota",
            "message": "quota denied",
            "detail": "exceeded namespace policy",
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
        self.assertIn("resourcequota", project.error_message)
        self.assertIn("quota denied", project.error_message)
        self.assertIn("exceeded namespace policy", project.error_message)
        mock_create_deployment.assert_not_called()
        mock_create_service.assert_not_called()

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_deployment_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
        }
        mock_create_resource_quota.return_value = {
            "status": "created",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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
        audit_actions = [
            log.action
            for log in self.db.query(AuditLog)
            .filter(AuditLog.project_id == project.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .all()
        ]
        self.assertEqual(
            audit_actions,
            [
                "PROJECT_CREATE_REQUESTED",
                "PROJECT_PROVISIONING_STARTED",
                "NAMESPACE_CREATED",
                "RESOURCE_QUOTA_CREATED",
                "DEPLOYMENT_CREATE_FAILED",
            ],
        )

    @patch("app.routers.projects.create_service")
    @patch("app.routers.projects.create_deployment")
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_marks_failed_when_service_creation_fails(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-prod",
        }
        mock_create_resource_quota.return_value = {
            "status": "created",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_create_project_rejects_duplicate_namespace(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "created",
            "namespace": "demo-api-dev",
        }
        mock_create_resource_quota.return_value = {
            "status": "created",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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
    @patch("app.routers.projects.create_resource_quota")
    @patch("app.routers.projects.create_namespace")
    def test_list_and_get_project_return_saved_projects(
        self,
        mock_create_namespace: MagicMock,
        mock_create_resource_quota: MagicMock,
        mock_create_deployment: MagicMock,
        mock_create_service: MagicMock,
    ) -> None:
        mock_create_namespace.return_value = {
            "status": "already_exists",
            "namespace": "demo-api-prod",
        }
        mock_create_resource_quota.return_value = {
            "status": "already_exists",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
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

    def test_get_project_audit_logs_returns_project_logs_in_created_order(self) -> None:
        project = Project(
            service_name="audit-demo",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="audit-demo-staging",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        create_audit_log(
            db=self.db,
            project_id=project.id,
            action="PROJECT_CREATE_REQUESTED",
            status="SUCCESS",
            message="created",
        )
        create_audit_log(
            db=self.db,
            project_id=project.id,
            action="PROJECT_RUNNING",
            status="SUCCESS",
            message="running",
        )

        logs = get_project_audit_logs(project_id=project.id, db=self.db)

        self.assertEqual(
            [log.action for log in logs],
            ["PROJECT_CREATE_REQUESTED", "PROJECT_RUNNING"],
        )

    def test_get_project_audit_logs_returns_404_for_missing_project(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            get_project_audit_logs(project_id=999, db=self.db)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Project not found: 999")

    def test_get_project_events_returns_404_for_missing_project(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            get_project_events(project_id=999, limit=50, db=self.db)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Project not found: 999")

    @patch("app.routers.projects.list_project_events")
    def test_get_project_events_returns_kubernetes_events(
        self,
        mock_list_project_events: MagicMock,
    ) -> None:
        project = Project(
            service_name="demo-api",
            environment="staging",
            image="nginx-not-exist-xyz:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="demo-api-staging",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        mock_list_project_events.return_value = [
            {
                "type": "Warning",
                "reason": "Failed",
                "message": "Failed to pull image",
                "count": 2,
                "involved_object_kind": "Pod",
                "involved_object_name": "demo-api-abc",
                "first_timestamp": "2026-07-05T07:00:00+00:00",
                "last_timestamp": "2026-07-05T07:01:00+00:00",
                "event_time": None,
                "source_component": "kubelet",
            }
        ]

        events = get_project_events(project_id=project.id, limit=20, db=self.db)

        self.assertEqual(events, mock_list_project_events.return_value)
        mock_list_project_events.assert_called_once_with(
            namespace="demo-api-staging",
            project_id=project.id,
            service_name="demo-api",
            limit=20,
        )

    @patch("app.routers.projects.list_project_events")
    def test_get_project_events_translates_kubernetes_errors(
        self,
        mock_list_project_events: MagicMock,
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
        mock_list_project_events.side_effect = RuntimeError("events unavailable")

        with self.assertRaises(HTTPException) as exc:
            get_project_events(project_id=project.id, limit=50, db=self.db)

        self.assertEqual(exc.exception.status_code, 500)
        self.assertEqual(exc.exception.detail, "events unavailable")

    @patch("app.routers.projects.delete_project_resources")
    def test_delete_project_marks_deleted_after_kubernetes_resources_are_removed(
        self,
        mock_delete_project_resources: MagicMock,
    ) -> None:
        project = Project(
            service_name="delete-demo",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="delete-demo-staging",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        def delete_results(*, namespace: str, service_name: str) -> list[dict]:
            deleting_project = self.db.get(Project, project.id)
            self.assertEqual(deleting_project.status, ProjectStatus.DELETING)
            self.assertIsNone(deleting_project.error_message)
            self.assertEqual(namespace, "delete-demo-staging")
            self.assertEqual(service_name, "delete-demo")
            return [
                {"status": "deleted", "resource": "ingress", "name": "delete-demo-ingress"},
                {"status": "deleted", "resource": "service", "name": "delete-demo-svc"},
                {"status": "deleted", "resource": "deployment", "name": "delete-demo"},
                {"status": "deleted", "resource": "resourcequota", "name": "portal-resource-quota"},
                {"status": "deleted", "resource": "namespace", "name": "delete-demo-staging"},
            ]

        mock_delete_project_resources.side_effect = delete_results

        deleted = delete_project(project_id=project.id, db=self.db)

        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        self.assertIsNone(deleted.error_message)
        mock_delete_project_resources.assert_called_once_with(
            namespace="delete-demo-staging",
            service_name="delete-demo",
        )
        with self.SessionLocal() as db:
            saved_project = db.get(Project, project.id)
            self.assertEqual(saved_project.status, ProjectStatus.DELETED)
            self.assertIsNone(saved_project.error_message)
            audit_actions = [
                log.action
                for log in db.query(AuditLog)
                .filter(AuditLog.project_id == project.id)
                .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
                .all()
            ]
            self.assertEqual(
                audit_actions,
                [
                    "PROJECT_DELETE_REQUESTED",
                    "INGRESS_DELETED",
                    "SERVICE_DELETED",
                    "DEPLOYMENT_DELETED",
                    "RESOURCE_QUOTA_DELETED",
                    "NAMESPACE_DELETED",
                    "PROJECT_DELETED",
                ],
            )

    @patch("app.routers.projects.delete_project_resources")
    def test_delete_project_returns_deleted_project_without_redeleting(
        self,
        mock_delete_project_resources: MagicMock,
    ) -> None:
        project = Project(
            service_name="delete-demo",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="delete-demo-staging",
            status=ProjectStatus.DELETED,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)

        deleted = delete_project(project_id=project.id, db=self.db)

        self.assertEqual(deleted.status, ProjectStatus.DELETED)
        mock_delete_project_resources.assert_not_called()

    @patch("app.routers.projects.delete_project_resources")
    def test_delete_project_marks_failed_when_any_resource_delete_fails(
        self,
        mock_delete_project_resources: MagicMock,
    ) -> None:
        project = Project(
            service_name="delete-demo",
            environment="staging",
            image="nginx:latest",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            expose_external=False,
            namespace="delete-demo-staging",
            status=ProjectStatus.RUNNING,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        mock_delete_project_resources.return_value = [
            {"status": "deleted", "resource": "service", "name": "delete-demo-svc"},
            {
                "status": "error",
                "resource": "deployment",
                "name": "delete-demo",
                "message": "Forbidden",
                "detail": "policy denied",
            },
            {"status": "not_found", "resource": "resourcequota", "name": "portal-resource-quota"},
        ]

        failed = delete_project(project_id=project.id, db=self.db)

        self.assertEqual(failed.status, ProjectStatus.FAILED)
        self.assertIn("deployment/delete-demo", failed.error_message)
        self.assertIn("Forbidden", failed.error_message)
        self.assertIn("policy denied", failed.error_message)

    def test_delete_project_returns_404_for_missing_project(self) -> None:
        with self.assertRaises(HTTPException) as exc:
            delete_project(project_id=999, db=self.db)

        self.assertEqual(exc.exception.status_code, 404)
        self.assertEqual(exc.exception.detail, "Project not found: 999")

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

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_resource_quota_sends_default_namespace_limits(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = create_resource_quota(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            environment="staging",
        )

        self.assertEqual(
            result,
            {
                "status": "created",
                "resource": "resourcequota",
                "name": "portal-resource-quota",
            },
        )
        mock_load_kube_config.assert_called_once()
        api.create_namespaced_resource_quota.assert_called_once()
        self.assertEqual(
            api.create_namespaced_resource_quota.call_args.kwargs["namespace"],
            "demo-api-staging",
        )
        quota = api.create_namespaced_resource_quota.call_args.kwargs["body"]
        self.assertEqual(quota.metadata.name, "portal-resource-quota")
        self.assertEqual(quota.metadata.namespace, "demo-api-staging")
        self.assertEqual(
            quota.metadata.labels,
            {
                "app.kubernetes.io/managed-by": "self-service-portal",
                "app.kubernetes.io/name": "demo-api",
                "platform.io/environment": "staging",
                "platform.io/project-id": "7",
            },
        )
        self.assertEqual(
            quota.spec.hard,
            {
                "requests.cpu": "4",
                "requests.memory": "4Gi",
                "limits.cpu": "8",
                "limits.memory": "8Gi",
                "pods": "10",
            },
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_resource_quota_reports_already_exists_for_conflict(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.create_namespaced_resource_quota.side_effect = ApiException(
            status=409,
            reason="Conflict",
        )

        result = create_resource_quota(
            namespace="demo-api-dev",
            project_id=3,
            service_name="demo-api",
            environment="dev",
        )

        self.assertEqual(
            result,
            {
                "status": "already_exists",
                "resource": "resourcequota",
                "name": "portal-resource-quota",
            },
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_resource_quota_returns_error_for_kubernetes_api_failure(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.create_namespaced_resource_quota.side_effect = ApiException(
            status=403,
            reason="Forbidden",
        )

        result = create_resource_quota(
            namespace="demo-api-prod",
            project_id=4,
            service_name="demo-api",
            environment="prod",
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["resource"], "resourcequota")
        self.assertEqual(result["message"], "Forbidden")

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

    def test_build_ingress_host_uses_localtest_domain(self) -> None:
        self.assertEqual(
            build_ingress_host("demo-api", "staging"),
            "demo-api-staging.localtest.me",
        )

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_ingress_sends_expected_networking_spec(
        self,
        mock_load_kube_config: MagicMock,
        mock_networking_v1_api: MagicMock,
    ) -> None:
        api = mock_networking_v1_api.return_value

        result = create_ingress(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            environment="staging",
            host="demo-api-staging.localtest.me",
        )

        self.assertEqual(
            result,
            {"status": "created", "resource": "ingress", "name": "demo-api-ingress"},
        )
        ingress = api.create_namespaced_ingress.call_args.kwargs["body"]
        self.assertEqual(api.create_namespaced_ingress.call_args.kwargs["namespace"], "demo-api-staging")
        self.assertEqual(ingress.metadata.name, "demo-api-ingress")
        self.assertEqual(ingress.metadata.namespace, "demo-api-staging")
        self.assertEqual(ingress.spec.rules[0].host, "demo-api-staging.localtest.me")
        path = ingress.spec.rules[0].http.paths[0]
        self.assertEqual(path.path, "/")
        self.assertEqual(path.path_type, "Prefix")
        self.assertEqual(path.backend.service.name, "demo-api-svc")
        self.assertEqual(path.backend.service.port.number, 80)

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_ingress_reports_already_exists_for_conflict(
        self,
        mock_load_kube_config: MagicMock,
        mock_networking_v1_api: MagicMock,
    ) -> None:
        api = mock_networking_v1_api.return_value
        api.create_namespaced_ingress.side_effect = ApiException(status=409, reason="Conflict")

        result = create_ingress(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            environment="staging",
            host="demo-api-staging.localtest.me",
        )

        self.assertEqual(
            result,
            {"status": "already_exists", "resource": "ingress", "name": "demo-api-ingress"},
        )

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_ingress_removes_ingress(
        self,
        mock_load_kube_config: MagicMock,
        mock_networking_v1_api: MagicMock,
    ) -> None:
        api = mock_networking_v1_api.return_value

        result = delete_ingress(namespace="delete-demo-staging", service_name="delete-demo")

        api.delete_namespaced_ingress.assert_called_once_with(
            name="delete-demo-ingress",
            namespace="delete-demo-staging",
        )
        self.assertEqual(
            result,
            {"status": "deleted", "resource": "ingress", "name": "delete-demo-ingress"},
        )

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_ingress_reports_not_found_as_already_absent(
        self,
        mock_load_kube_config: MagicMock,
        mock_networking_v1_api: MagicMock,
    ) -> None:
        api = mock_networking_v1_api.return_value
        api.delete_namespaced_ingress.side_effect = ApiException(status=404, reason="Not Found")

        result = delete_ingress(namespace="delete-demo-staging", service_name="delete-demo")

        self.assertEqual(
            result,
            {"status": "not_found", "resource": "ingress", "name": "delete-demo-ingress"},
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_service_removes_cluster_ip_service(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = delete_service(namespace="delete-demo-staging", service_name="delete-demo")

        api.delete_namespaced_service.assert_called_once_with(
            name="delete-demo-svc",
            namespace="delete-demo-staging",
        )
        self.assertEqual(
            result,
            {"status": "deleted", "resource": "service", "name": "delete-demo-svc"},
        )

    @patch("app.k8s_client.client.AppsV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_deployment_removes_workload(
        self,
        mock_load_kube_config: MagicMock,
        mock_apps_v1_api: MagicMock,
    ) -> None:
        api = mock_apps_v1_api.return_value

        result = delete_deployment(namespace="delete-demo-staging", service_name="delete-demo")

        api.delete_namespaced_deployment.assert_called_once_with(
            name="delete-demo",
            namespace="delete-demo-staging",
        )
        self.assertEqual(
            result,
            {"status": "deleted", "resource": "deployment", "name": "delete-demo"},
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_resource_quota_removes_portal_quota(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = delete_resource_quota(namespace="delete-demo-staging")

        api.delete_namespaced_resource_quota.assert_called_once_with(
            name="portal-resource-quota",
            namespace="delete-demo-staging",
        )
        self.assertEqual(
            result,
            {"status": "deleted", "resource": "resourcequota", "name": "portal-resource-quota"},
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_namespace_removes_project_namespace(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value

        result = delete_namespace(namespace="delete-demo-staging")

        api.delete_namespace.assert_called_once_with(name="delete-demo-staging")
        self.assertEqual(
            result,
            {"status": "deleted", "resource": "namespace", "name": "delete-demo-staging"},
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_service_reports_not_found_as_already_absent(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.delete_namespaced_service.side_effect = ApiException(
            status=404,
            reason="Not Found",
        )

        result = delete_service(namespace="delete-demo-staging", service_name="delete-demo")

        self.assertEqual(
            result,
            {"status": "not_found", "resource": "service", "name": "delete-demo-svc"},
        )

    @patch("app.k8s_client.delete_namespace")
    @patch("app.k8s_client.delete_resource_quota")
    @patch("app.k8s_client.delete_deployment")
    @patch("app.k8s_client.delete_service")
    @patch("app.k8s_client.delete_ingress")
    def test_delete_project_resources_deletes_in_expected_order(
        self,
        mock_delete_ingress: MagicMock,
        mock_delete_service: MagicMock,
        mock_delete_deployment: MagicMock,
        mock_delete_resource_quota: MagicMock,
        mock_delete_namespace: MagicMock,
    ) -> None:
        call_order = []
        mock_delete_ingress.side_effect = lambda **kwargs: call_order.append("ingress") or {
            "status": "deleted",
            "resource": "ingress",
            "name": "delete-demo-ingress",
        }
        mock_delete_service.side_effect = lambda **kwargs: call_order.append("service") or {
            "status": "deleted",
            "resource": "service",
            "name": "delete-demo-svc",
        }
        mock_delete_deployment.side_effect = lambda **kwargs: call_order.append("deployment") or {
            "status": "deleted",
            "resource": "deployment",
            "name": "delete-demo",
        }
        mock_delete_resource_quota.side_effect = lambda **kwargs: call_order.append("resourcequota") or {
            "status": "deleted",
            "resource": "resourcequota",
            "name": "portal-resource-quota",
        }
        mock_delete_namespace.side_effect = lambda **kwargs: call_order.append("namespace") or {
            "status": "deleted",
            "resource": "namespace",
            "name": "delete-demo-staging",
        }

        results = delete_project_resources(
            namespace="delete-demo-staging",
            service_name="delete-demo",
        )

        self.assertEqual(call_order, ["ingress", "service", "deployment", "resourcequota", "namespace"])
        self.assertEqual([result["resource"] for result in results], [
            "ingress",
            "service",
            "deployment",
            "resourcequota",
            "namespace",
        ])

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

    def _event(
        self,
        *,
        name: str,
        kind: str = "Pod",
        reason: str = "Scheduled",
        last_timestamp: datetime | None = None,
        event_time: datetime | None = None,
        creation_timestamp: datetime | None = None,
        first_timestamp: datetime | None = None,
    ) -> MagicMock:
        event = MagicMock()
        event.type = "Normal"
        event.reason = reason
        event.message = f"{reason} message"
        event.count = 1
        event.first_timestamp = first_timestamp
        event.last_timestamp = last_timestamp
        event.event_time = event_time
        event.involved_object.kind = kind
        event.involved_object.name = name
        event.source.component = "kubelet"
        event.metadata.creation_timestamp = creation_timestamp
        return event

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_events_filters_unrelated_events(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        pod = MagicMock()
        pod.metadata.name = "demo-api-abc"
        api.list_namespaced_pod.return_value.items = [pod]
        api.list_namespaced_event.return_value.items = [
            self._event(name="demo-api-abc", reason="Scheduled"),
            self._event(name="other-api-abc", reason="Failed"),
        ]

        events = list_project_events(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
        )

        api.list_namespaced_pod.assert_called_once_with(
            namespace="demo-api-staging",
            label_selector="platform.io/project-id=7",
        )
        self.assertEqual([event["reason"] for event in events], ["Scheduled"])

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_events_includes_managed_object_names_and_prefixes(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        pod = MagicMock()
        pod.metadata.name = "demo-api-pod"
        api.list_namespaced_pod.return_value.items = [pod]
        api.list_namespaced_event.return_value.items = [
            self._event(name="demo-api", kind="Deployment", reason="ScalingReplicaSet"),
            self._event(name="demo-api-svc", kind="Service", reason="Created"),
            self._event(name="demo-api-abc123", kind="ReplicaSet", reason="SuccessfulCreate"),
        ]

        events = list_project_events(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
        )

        self.assertEqual(
            [event["involved_object_name"] for event in events],
            ["demo-api", "demo-api-svc", "demo-api-abc123"],
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_events_sorts_latest_first_and_applies_limit(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.list_namespaced_pod.return_value.items = []
        api.list_namespaced_event.return_value.items = [
            self._event(
                name="demo-api",
                reason="old",
                last_timestamp=datetime(2026, 7, 5, 7, 0, tzinfo=timezone.utc),
            ),
            self._event(
                name="demo-api",
                reason="newest",
                event_time=datetime(2026, 7, 5, 7, 2, tzinfo=timezone.utc),
            ),
            self._event(
                name="demo-api",
                reason="middle",
                creation_timestamp=datetime(2026, 7, 5, 7, 1, tzinfo=timezone.utc),
            ),
        ]

        events = list_project_events(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
            limit=2,
        )

        self.assertEqual([event["reason"] for event in events], ["newest", "middle"])

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_events_formats_timestamps_as_iso_strings(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.list_namespaced_pod.return_value.items = []
        api.list_namespaced_event.return_value.items = [
            self._event(
                name="demo-api",
                reason="Failed",
                first_timestamp=datetime(2026, 7, 5, 7, 0, tzinfo=timezone.utc),
                last_timestamp=datetime(2026, 7, 5, 7, 1, tzinfo=timezone.utc),
                event_time=datetime(2026, 7, 5, 7, 2, tzinfo=timezone.utc),
            )
        ]

        event = list_project_events(
            namespace="demo-api-staging",
            project_id=7,
            service_name="demo-api",
        )[0]

        self.assertEqual(event["first_timestamp"], "2026-07-05T07:00:00+00:00")
        self.assertEqual(event["last_timestamp"], "2026-07-05T07:01:00+00:00")
        self.assertEqual(event["event_time"], "2026-07-05T07:02:00+00:00")
        self.assertEqual(event["source_component"], "kubelet")

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_project_events_converts_kubernetes_api_errors(
        self,
        mock_load_kube_config: MagicMock,
        mock_core_v1_api: MagicMock,
    ) -> None:
        api = mock_core_v1_api.return_value
        api.list_namespaced_pod.side_effect = ApiException(
            status=403,
            reason="Forbidden",
        )

        with self.assertRaises(RuntimeError) as exc:
            list_project_events(
                namespace="demo-api-staging",
                project_id=7,
                service_name="demo-api",
            )

        self.assertEqual(str(exc.exception), "Kubernetes API error: Forbidden")

if __name__ == "__main__":
    unittest.main()
