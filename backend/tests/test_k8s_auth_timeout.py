import base64
import unittest
from unittest.mock import MagicMock, patch

import app.k8s_auth as k8s_auth
from app.config import Settings


class FakeCredentials:
    token = "initial-token"
    expired = False
    valid = True

    def refresh(self, request) -> None:
        self.token = "refreshed-token"
        self.expired = False
        self.valid = True


class KubernetesAuthenticationTimeoutTests(unittest.TestCase):
    def tearDown(self) -> None:
        k8s_auth.close_cached_api_client()

    def test_container_api_discovery_uses_finite_connect_and_read_timeout(self) -> None:
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "masterAuth": {
                "clusterCaCertificate": base64.b64encode(b"test-ca").decode("ascii")
            }
        }
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
            patch(
                "app.k8s_auth.google.auth.default",
                return_value=(FakeCredentials(), None),
            ),
            patch(
                "app.k8s_auth.AuthorizedSession",
                return_value=authorized_session,
            ),
        ):
            k8s_auth.build_api_client(settings)

        self.assertEqual(
            authorized_session.get.call_args.kwargs.get("timeout"),
            (3.05, 10.0),
        )


if __name__ == "__main__":
    unittest.main()
