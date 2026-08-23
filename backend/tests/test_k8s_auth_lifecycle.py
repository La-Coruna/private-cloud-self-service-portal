from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import app.k8s_auth as k8s_auth
from app.config import Settings


class FakeCredentials:
    def __init__(self) -> None:
        self.token = "initial-token"
        self.expired = False
        self.valid = True

    def refresh(self, request) -> None:
        self.token = "refreshed-token"
        self.expired = False
        self.valid = True


class KubernetesAuthenticationLifecycleTests(unittest.TestCase):
    def test_repeated_gke_builds_reuse_client_without_creating_a_ca_file(self) -> None:
        cleanup = getattr(k8s_auth, "close_cached_api_client", None)
        self.assertIsNotNone(cleanup, "GKE client lifecycle cleanup is missing")
        cleanup()
        self.addCleanup(cleanup)

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
        real_mkstemp = tempfile.mkstemp

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch(
                    "app.k8s_auth.google.auth.default",
                    return_value=(credentials, None),
                ),
                patch(
                    "app.k8s_auth.AuthorizedSession",
                    return_value=authorized_session,
                ),
                patch(
                    "app.k8s_auth.tempfile.mkstemp",
                    side_effect=lambda **kwargs: real_mkstemp(dir=temp_dir, **kwargs),
                ) as mkstemp,
                patch("app.k8s_auth.os.chmod") as chmod,
            ):
                first_client = k8s_auth.build_api_client(settings)
                second_client = k8s_auth.build_api_client(settings)

                ca_files = list(Path(temp_dir).iterdir())
                self.assertIs(second_client, first_client)
                self.assertEqual(ca_files, [])
                mkstemp.assert_not_called()
                chmod.assert_not_called()
                authorized_session.close.assert_called_once_with()

                cleanup()


if __name__ == "__main__":
    unittest.main()
