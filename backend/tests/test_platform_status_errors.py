import unittest
from unittest.mock import MagicMock, patch

from requests.exceptions import Timeout

from app.config import Settings
from app.domain import PlatformAvailability
from app.services.platform_status import PlatformStatusService


SANITIZED_MESSAGE = "Kubernetes API is temporarily unavailable"


class PlatformStatusErrorHandlingTests(unittest.TestCase):
    def test_container_discovery_timeout_is_sanitized_as_unavailable(self) -> None:
        settings = Settings(kube_auth_mode="gke")
        with patch(
            "app.services.platform_status.build_api_client",
            side_effect=Timeout("internal-cluster.example:443 timed out"),
        ):
            result = PlatformStatusService(settings=settings).get_status()

        self.assertEqual(result.status, PlatformAvailability.UNAVAILABLE)
        self.assertFalse(result.creation_allowed)
        self.assertEqual(result.message, SANITIZED_MESSAGE)
        self.assertNotIn("internal-cluster.example", result.message)

    def test_unexpected_programming_error_surfaces(self) -> None:
        core_v1_api = MagicMock()
        core_v1_api.list_node.side_effect = RuntimeError("programming defect")

        with self.assertRaisesRegex(RuntimeError, "programming defect"):
            PlatformStatusService(core_v1_api=core_v1_api).get_status()


if __name__ == "__main__":
    unittest.main()
