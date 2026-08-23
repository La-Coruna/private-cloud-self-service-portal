import unittest
from unittest.mock import MagicMock, patch
from kubernetes import client

from app.config import Settings
from app.k8s_auth import CLOUD_PLATFORM_SCOPE, build_api_client


class FakeCredentials:
    def __init__(self, token: str = "initial-token") -> None:
        self.token = token
        self.expired = False
        self.valid = True
        self.refresh_calls = []

    def refresh(self, request) -> None:
        self.refresh_calls.append(request)
        self.token = "refreshed-token"
        self.expired = False
        self.valid = True


class KubernetesAuthenticationTests(unittest.TestCase):
    def test_local_mode_loads_the_named_kubeconfig_context(self) -> None:
        settings = Settings(
            kube_auth_mode="local",
            kube_context="kind-portal-dev",
        )

        with patch("app.k8s_auth.config.load_kube_config") as load_kube_config:
            api_client = build_api_client(settings)

        self.addCleanup(api_client.close)
        load_kube_config.assert_called_once_with(context="kind-portal-dev")

    def test_gke_mode_uses_adc_dns_endpoint_and_system_ca_trust(self) -> None:
        credentials = FakeCredentials()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {}
        authorized_session = MagicMock()
        authorized_session.get.return_value = response
        settings = Settings(
            kube_auth_mode="gke",
            firestore_project_id="portal-project",
            gke_cluster_location="asia-northeast3-a",
            gke_cluster_name="portal-cluster",
            gke_dns_endpoint="https://portal-cluster.example.gke.goog",
        )

        with (
            patch("app.k8s_auth.google.auth.default", return_value=(credentials, None))
            as default_credentials,
            patch(
                "app.k8s_auth.AuthorizedSession", return_value=authorized_session
            ),
        ):
            api_client = build_api_client(settings)

        self.addCleanup(api_client.close)
        default_credentials.assert_called_once_with(scopes=[CLOUD_PLATFORM_SCOPE])
        self.assertEqual(
            api_client.configuration.host,
            "https://portal-cluster.example.gke.goog",
        )
        self.assertIsNone(api_client.configuration.ssl_ca_cert)
        self.assertEqual(
            authorized_session.get.call_args.args[0],
            "https://container.googleapis.com/v1/projects/portal-project/locations/"
            "asia-northeast3-a/clusters/portal-cluster",
        )

    def test_expired_gke_credentials_refresh_before_the_next_kubernetes_request(self) -> None:
        credentials = FakeCredentials()
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {}
        authorized_session = MagicMock()
        authorized_session.get.return_value = response
        settings = Settings(
            kube_auth_mode="gke",
            firestore_project_id="portal-project",
            gke_cluster_location="asia-northeast3-a",
            gke_cluster_name="portal-cluster",
            gke_dns_endpoint="https://portal-cluster.example.gke.goog",
        )
        refresh_request = object()

        with (
            patch("app.k8s_auth.google.auth.default", return_value=(credentials, None)),
            patch(
                "app.k8s_auth.AuthorizedSession", return_value=authorized_session
            ),
            patch("app.k8s_auth.Request", return_value=refresh_request),
        ):
            api_client = build_api_client(settings)
            self.addCleanup(api_client.close)
            credentials.expired = True
            credentials.valid = False
            transport_response = object()
            api_client.rest_client.GET = MagicMock(return_value=transport_response)

            operation_response = client.CoreV1Api(api_client=api_client).list_namespace(
                _preload_content=False
            )

        self.assertIs(operation_response, transport_response)
        self.assertEqual(credentials.refresh_calls, [refresh_request])
        self.assertEqual(
            api_client.rest_client.GET.call_args.kwargs["headers"]["authorization"],
            "Bearer refreshed-token",
        )
        self.assertEqual(
            api_client.configuration.api_key["authorization"],
            "refreshed-token",
        )


if __name__ == "__main__":
    unittest.main()
