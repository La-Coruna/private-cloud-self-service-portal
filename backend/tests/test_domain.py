import unittest
from dataclasses import replace
from datetime import datetime

from app.domain import AuditLog, PlatformAvailability, Project, ProjectStatus, utc_now
from app.schemas import AuditLogResponse, ProjectCreateRequest, ProjectResponse


def make_request() -> ProjectCreateRequest:
    return ProjectCreateRequest(
        service_name="api",
        environment="staging",
        image="nginx:1.27",
        replicas=2,
        cpu_request="250m",
        cpu_limit="1",
        memory_request="256Mi",
        memory_limit="1Gi",
        expose_external=True,
    )


class DomainTests(unittest.TestCase):
    def test_project_statuses_are_stable(self) -> None:
        self.assertEqual(
            [status.value for status in ProjectStatus],
            ["REQUESTED", "PROVISIONING", "RUNNING", "FAILED", "DELETING", "DELETED"],
        )

    def test_platform_availability_values_are_stable(self) -> None:
        self.assertEqual(
            [availability.value for availability in PlatformAvailability],
            ["AVAILABLE", "RECOVERING", "UNAVAILABLE"],
        )

    def test_project_new_uses_namespace_as_its_string_identifier(self) -> None:
        project = Project.new(request=make_request(), namespace="demo-api-staging")

        self.assertEqual(project.id, "demo-api-staging")
        self.assertEqual(project.namespace, project.id)
        self.assertEqual(project.service_name, "api")
        self.assertEqual(project.environment, "staging")
        self.assertEqual(project.image, "nginx:1.27")
        self.assertEqual(project.replicas, 2)
        self.assertEqual(project.cpu_request, "250m")
        self.assertEqual(project.cpu_limit, "1")
        self.assertEqual(project.memory_request, "256Mi")
        self.assertEqual(project.memory_limit, "1Gi")
        self.assertTrue(project.expose_external)
        self.assertIsNone(project.ingress_host)
        self.assertEqual(project.status, ProjectStatus.REQUESTED)
        self.assertIsNone(project.error_message)
        self.assertFalse(project.capacity_claimed)
        self.assertIsInstance(project.created_at, datetime)
        self.assertEqual(project.created_at, project.updated_at)

    def test_domain_records_and_response_models_keep_string_project_ids(self) -> None:
        created_at = utc_now()
        audit_log = AuditLog(
            id="log-1",
            project_id="demo-api-staging",
            action="PROJECT_CREATED",
            status="SUCCESS",
            message=None,
            created_at=created_at,
        )
        project = Project.new(request=make_request(), namespace="demo-api-staging")

        self.assertEqual(ProjectResponse.model_validate(project).id, "demo-api-staging")
        self.assertEqual(AuditLogResponse.model_validate(audit_log).project_id, "demo-api-staging")

    def test_owner_token_must_not_be_empty_or_whitespace(self) -> None:
        project = Project.new(request=make_request(), namespace="demo-api-staging")

        for invalid in ("", "   "):
            with self.subTest(owner_token=invalid):
                with self.assertRaisesRegex(ValueError, "owner_token"):
                    replace(project, owner_token=invalid)

    def test_owner_token_cannot_change_after_construction(self) -> None:
        project = Project.new(request=make_request(), namespace="demo-api-staging")
        original_token = project.owner_token

        with self.assertRaisesRegex(AttributeError, "owner_token"):
            project.owner_token = "different-owner"

        self.assertEqual(project.owner_token, original_token)


if __name__ == "__main__":
    unittest.main()
