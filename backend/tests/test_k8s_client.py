import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import inspect
import unittest
from unittest.mock import MagicMock, call, patch

from kubernetes.client import ApiException

from app.k8s_client import (
    KubernetesUnavailableError,
    build_common_labels,
    build_selector_labels,
    create_deployment,
    create_ingress,
    create_namespace,
    create_resource_quota,
    create_service,
    delete_project_resources,
    delete_deployment,
    delete_ingress,
    delete_namespace,
    delete_resource_quota,
    delete_service,
    list_project_events,
    list_project_pods,
    load_kube_config,
    verify_project_resources,
)


PROJECT_ID = "demo-api-staging"
OWNER_TOKEN = "owner-token-123"


class FakeNamespaceCluster:
    def __init__(self, namespaces):
        self.namespaces = copy.deepcopy(namespaces)
        self.delete_calls = []

    def create_namespace(self, body):
        name = body.metadata.name
        if name in self.namespaces:
            raise ApiException(status=409, reason="Conflict")
        self.namespaces[name] = copy.deepcopy(body)

    def read_namespace(self, name):
        if name not in self.namespaces:
            raise ApiException(status=404, reason="Not Found")
        return copy.deepcopy(self.namespaces[name])

    def delete_namespace(self, name):
        self.delete_calls.append(name)
        if name not in self.namespaces:
            raise ApiException(status=404, reason="Not Found")
        del self.namespaces[name]


class KubernetesClientTests(unittest.TestCase):
    @patch("app.k8s_client.client.Configuration.set_default")
    @patch("app.k8s_client.build_api_client")
    @patch("app.k8s_client.get_settings")
    def test_shared_entry_uses_configured_api_client(
        self,
        settings,
        build_api_client,
        set_default,
    ) -> None:
        configured = MagicMock()
        api_client = SimpleNamespace(configuration=configured)
        settings.return_value = SimpleNamespace(kube_context="kind-portal-dev")
        build_api_client.return_value = api_client

        load_kube_config()

        build_api_client.assert_called_once_with(settings.return_value)
        set_default.assert_called_once_with(configured)

    def test_project_id_annotations_and_labels_use_namespace_strings(self) -> None:
        self.assertIs(inspect.signature(build_common_labels).parameters["project_id"].annotation, str)
        self.assertIs(inspect.signature(list_project_pods).parameters["project_id"].annotation, str)
        self.assertEqual(
            build_selector_labels(PROJECT_ID, "api"),
            {
                "app.kubernetes.io/name": "api",
                "platform.io/project-id": PROJECT_ID,
            },
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_namespace_sends_string_id_labels(self, load_config, core_api) -> None:
        api = core_api.return_value

        result = create_namespace(
            PROJECT_ID, PROJECT_ID, "api", "staging", OWNER_TOKEN
        )

        self.assertEqual(result, {"status": "created", "namespace": PROJECT_ID})
        body = api.create_namespace.call_args.args[0]
        self.assertEqual(body.metadata.name, PROJECT_ID)
        self.assertEqual(body.metadata.labels["platform.io/project-id"], PROJECT_ID)
        self.assertEqual(body.metadata.labels["platform.io/environment"], "staging")
        self.assertEqual(body.metadata.labels["platform.io/owner-token"], OWNER_TOKEN)
        load_config.assert_called_once_with()

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_create_namespace_maps_409_to_already_exists(self, load_config, core_api) -> None:
        api = core_api.return_value
        created = {}

        def conflict(body):
            created["body"] = body
            raise ApiException(status=409, reason="Conflict")

        api.create_namespace.side_effect = conflict
        api.read_namespace.side_effect = lambda name: created["body"]

        result = create_namespace(
            PROJECT_ID, PROJECT_ID, "api", "staging", OWNER_TOKEN
        )

        self.assertEqual(result, {"status": "already_exists", "namespace": PROJECT_ID})

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_legacy_namespace_conflict_is_neither_adopted_nor_deleted(
        self,
        load_config,
        core_api,
    ) -> None:
        legacy = {
            PROJECT_ID: __import__("kubernetes").client.V1Namespace(
                metadata=__import__("kubernetes").client.V1ObjectMeta(
                    name=PROJECT_ID,
                    labels={
                        "app.kubernetes.io/managed-by": "legacy-portal",
                        "platform.io/project-id": PROJECT_ID,
                    },
                )
            )
        }
        cluster = FakeNamespaceCluster(legacy)
        core_api.return_value = cluster

        create_result = create_namespace(
            PROJECT_ID,
            PROJECT_ID,
            "api",
            "staging",
            OWNER_TOKEN,
        )
        delete_result = verify_project_resources(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
            owner_token=OWNER_TOKEN,
            image="nginx:1.27",
            replicas=1,
            cpu_request="100m",
            cpu_limit="500m",
            memory_request="128Mi",
            memory_limit="512Mi",
            ingress_host=None,
        )

        self.assertEqual(create_result["status"], "error")
        self.assertEqual(create_result["reason"], "ownership_conflict")
        self.assertEqual(delete_result["status"], "error")
        self.assertEqual(delete_result["reason"], "ownership_conflict")
        self.assertEqual(cluster.delete_calls, [])
        self.assertEqual(cluster.namespaces, legacy)

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_resource_quota_contains_expected_limits(self, load_config, core_api) -> None:
        result = create_resource_quota(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
        )

        self.assertEqual(result["status"], "created")
        kwargs = core_api.return_value.create_namespaced_resource_quota.call_args.kwargs
        self.assertEqual(kwargs["namespace"], PROJECT_ID)
        self.assertEqual(kwargs["body"].spec.hard["pods"], "10")
        self.assertEqual(
            kwargs["body"].metadata.labels["platform.io/project-id"],
            PROJECT_ID,
        )

    @patch("app.k8s_client.client.AppsV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_deployment_contains_selector_image_and_resources(self, load_config, apps_api) -> None:
        result = create_deployment(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
            image="nginx:1.27",
            replicas=2,
            cpu_request="250m",
            cpu_limit="1",
            memory_request="256Mi",
            memory_limit="1Gi",
        )

        self.assertEqual(result["status"], "created")
        body = apps_api.return_value.create_namespaced_deployment.call_args.kwargs["body"]
        self.assertEqual(body.spec.replicas, 2)
        self.assertEqual(body.spec.selector.match_labels["platform.io/project-id"], PROJECT_ID)
        container = body.spec.template.spec.containers[0]
        self.assertEqual(container.image, "nginx:1.27")
        self.assertEqual(container.resources.requests, {"cpu": "250m", "memory": "256Mi"})
        self.assertEqual(container.resources.limits, {"cpu": "1", "memory": "1Gi"})

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_service_contains_cluster_ip_selector(self, load_config, core_api) -> None:
        result = create_service(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
        )

        self.assertEqual(result["name"], "api-svc")
        body = core_api.return_value.create_namespaced_service.call_args.kwargs["body"]
        self.assertEqual(body.spec.type, "ClusterIP")
        self.assertEqual(body.spec.selector["platform.io/project-id"], PROJECT_ID)
        self.assertEqual(body.spec.ports[0].port, 80)

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    @patch("app.k8s_client.get_settings")
    def test_ingress_contains_configured_class_host_and_backend(
        self,
        settings,
        load_config,
        networking_api,
    ) -> None:
        settings.return_value = SimpleNamespace(app_ingress_class_name="nginx")

        result = create_ingress(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
            host="api-staging.example.test",
        )

        self.assertEqual(result["status"], "created")
        body = networking_api.return_value.create_namespaced_ingress.call_args.kwargs["body"]
        self.assertEqual(body.spec.ingress_class_name, "nginx")
        self.assertEqual(body.spec.rules[0].host, "api-staging.example.test")
        backend = body.spec.rules[0].http.paths[0].backend.service
        self.assertEqual(backend.name, "api-svc")
        self.assertEqual(backend.port.number, 80)

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_delete_service_maps_404_to_already_absent(self, load_config, core_api) -> None:
        core_api.return_value.delete_namespaced_service.side_effect = ApiException(
            status=404,
            reason="Not Found",
        )

        result = delete_service(PROJECT_ID, "api")

        self.assertEqual(
            result,
            {"status": "not_found", "resource": "service", "name": "api-svc"},
        )

    @patch("app.k8s_client.delete_namespace")
    @patch("app.k8s_client.delete_resource_quota")
    @patch("app.k8s_client.delete_deployment")
    @patch("app.k8s_client.delete_service")
    @patch("app.k8s_client.delete_ingress")
    def test_delete_project_resources_preserves_reverse_resource_order(
        self,
        ingress,
        service,
        deployment,
        quota,
        namespace,
    ) -> None:
        calls = []
        for mock, resource in (
            (ingress, "ingress"),
            (service, "service"),
            (deployment, "deployment"),
            (quota, "resourcequota"),
            (namespace, "namespace"),
        ):
            mock.side_effect = lambda *args, _resource=resource, **kwargs: calls.append(_resource) or {"resource": _resource}

        results = delete_project_resources(PROJECT_ID, "api")

        self.assertEqual(calls, ["ingress", "service", "deployment", "resourcequota", "namespace"])
        self.assertEqual([result["resource"] for result in results], calls)

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_list_pods_formats_container_statuses(self, load_config, core_api) -> None:
        running = SimpleNamespace(running=SimpleNamespace(), waiting=None, terminated=None)
        container_status = SimpleNamespace(
            name="api",
            image="nginx:1.27",
            ready=True,
            restart_count=2,
            state=running,
        )
        pod = SimpleNamespace(
            metadata=SimpleNamespace(name="api-abc", namespace=PROJECT_ID),
            spec=SimpleNamespace(node_name="spot-node-1"),
            status=SimpleNamespace(
                phase="Running",
                pod_ip="10.0.0.2",
                start_time=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
                container_statuses=[container_status],
            ),
        )
        core_api.return_value.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

        result = list_project_pods(PROJECT_ID, PROJECT_ID)

        self.assertEqual(result[0]["name"], "api-abc")
        self.assertEqual(result[0]["start_time"], "2026-08-12T09:30:00+00:00")
        self.assertEqual(
            result[0]["containers"][0],
            {
                "name": "api",
                "image": "nginx:1.27",
                "ready": True,
                "restart_count": 2,
                "state": "running",
                "reason": None,
                "message": None,
            },
        )
        core_api.return_value.list_namespaced_pod.assert_called_once_with(
            namespace=PROJECT_ID,
            label_selector=f"platform.io/project-id={PROJECT_ID}",
        )

    @staticmethod
    def _event(name: str, reason: str, when: datetime):
        return SimpleNamespace(
            type="Warning",
            reason=reason,
            message=f"message-{reason}",
            count=1,
            involved_object=SimpleNamespace(kind="Pod", name=name),
            first_timestamp=when - timedelta(seconds=1),
            last_timestamp=when,
            event_time=None,
            source=SimpleNamespace(component="kubelet"),
            metadata=SimpleNamespace(creation_timestamp=when),
        )

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_events_filter_sort_limit_and_format_timestamps(self, load_config, core_api) -> None:
        api = core_api.return_value
        api.list_namespaced_pod.return_value = SimpleNamespace(
            items=[SimpleNamespace(metadata=SimpleNamespace(name="api-pod"))]
        )
        base = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
        api.list_namespaced_event.return_value = SimpleNamespace(
            items=[
                self._event("unrelated", "Ignored", base + timedelta(seconds=4)),
                self._event("api-pod", "Older", base),
                self._event("api-worker", "Newest", base + timedelta(seconds=2)),
                self._event("api-svc", "Middle", base + timedelta(seconds=1)),
            ]
        )

        result = list_project_events(PROJECT_ID, PROJECT_ID, "api", limit=2)

        self.assertEqual([event["reason"] for event in result], ["Newest", "Middle"])
        self.assertEqual(result[0]["last_timestamp"], "2026-08-12T10:00:02+00:00")
        self.assertEqual(result[0]["source_component"], "kubelet")

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_expected_pod_api_error_is_typed_and_programming_error_surfaces(
        self,
        load_config,
        core_api,
    ) -> None:
        api = core_api.return_value
        api.list_namespaced_pod.side_effect = ApiException(status=503, reason="Unavailable")
        with self.assertRaises(KubernetesUnavailableError):
            list_project_pods(PROJECT_ID, PROJECT_ID)

        api.list_namespaced_pod.side_effect = ValueError("programming defect")
        with self.assertRaisesRegex(ValueError, "programming defect"):
            list_project_pods(PROJECT_ID, PROJECT_ID)

    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_resource_quota_maps_409_to_already_exists(self, load_config, core_api) -> None:
        api = core_api.return_value
        created = {}

        def conflict(*, namespace, body):
            created["body"] = body
            raise ApiException(status=409, reason="Conflict")

        api.create_namespaced_resource_quota.side_effect = conflict
        api.read_namespaced_resource_quota.side_effect = (
            lambda **kwargs: created["body"]
        )

        result = create_resource_quota(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
        )

        self.assertEqual(result["status"], "already_exists")
        self.assertEqual(result["name"], "portal-resource-quota")

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.load_kube_config")
    @patch("app.k8s_client.get_settings")
    def test_ingress_maps_409_to_already_exists(
        self, settings, load_config, networking_api
    ) -> None:
        settings.return_value = SimpleNamespace(app_ingress_class_name="nginx")
        api = networking_api.return_value
        created = {}

        def conflict(*, namespace, body):
            created["body"] = body
            raise ApiException(status=409, reason="Conflict")

        api.create_namespaced_ingress.side_effect = conflict
        api.read_namespaced_ingress.side_effect = lambda **kwargs: created["body"]

        result = create_ingress(
            namespace=PROJECT_ID,
            project_id=PROJECT_ID,
            service_name="api",
            environment="staging",
            host="api-staging.example.test",
        )

        self.assertEqual(result["status"], "already_exists")
        self.assertEqual(result["name"], "api-ingress")

    @patch("app.k8s_client.client.NetworkingV1Api")
    @patch("app.k8s_client.client.AppsV1Api")
    @patch("app.k8s_client.client.CoreV1Api")
    @patch("app.k8s_client.load_kube_config")
    def test_individual_delete_helpers_call_expected_kubernetes_methods(
        self, load_config, core_api, apps_api, networking_api
    ) -> None:
        results = [
            delete_ingress(PROJECT_ID, "api"),
            delete_service(PROJECT_ID, "api"),
            delete_deployment(PROJECT_ID, "api"),
            delete_resource_quota(PROJECT_ID),
            delete_namespace(PROJECT_ID),
        ]

        self.assertEqual(
            [result["resource"] for result in results],
            ["ingress", "service", "deployment", "resourcequota", "namespace"],
        )
        networking_api.return_value.delete_namespaced_ingress.assert_called_once_with(
            name="api-ingress", namespace=PROJECT_ID
        )
        core_api.return_value.delete_namespaced_service.assert_called_once_with(
            name="api-svc", namespace=PROJECT_ID
        )
        apps_api.return_value.delete_namespaced_deployment.assert_called_once_with(
            name="api", namespace=PROJECT_ID
        )
        core_api.return_value.delete_namespaced_resource_quota.assert_called_once_with(
            name="portal-resource-quota", namespace=PROJECT_ID
        )
        core_api.return_value.delete_namespace.assert_called_once_with(name=PROJECT_ID)


if __name__ == "__main__":
    unittest.main()
