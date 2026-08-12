import unittest
from unittest.mock import patch

from kubernetes.config.config_exception import ConfigException

from app.config import Settings
from app.k8s_auth import build_api_client


class LocalKubernetesAuthenticationValidationTests(unittest.TestCase):
    def test_local_mode_rejects_an_empty_named_context(self) -> None:
        settings = Settings(kube_auth_mode="local", kube_context="")

        with (
            patch("app.k8s_auth.config.load_kube_config") as load_kube_config,
            patch("app.k8s_auth.client.ApiClient"),
            self.assertRaisesRegex(ConfigException, "named kube context"),
        ):
            build_api_client(settings)

        load_kube_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
