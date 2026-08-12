from datetime import datetime
import unittest
from unittest.mock import MagicMock

from kubernetes import client
from kubernetes.client import ApiException

from app.domain import PlatformAvailability
from app.services.platform_status import PlatformStatusService


def make_node(
    *,
    ready: bool,
    unschedulable: bool = False,
    taints: list[client.V1Taint] | None = None,
) -> client.V1Node:
    return client.V1Node(
        metadata=client.V1ObjectMeta(
            name="spot-node-1",
            labels={"cloud.google.com/gke-spot": "true"},
        ),
        spec=client.V1NodeSpec(
            unschedulable=unschedulable,
            taints=taints,
        ),
        status=client.V1NodeStatus(
            conditions=[
                client.V1NodeCondition(
                    type="Ready",
                    status="True" if ready else "False",
                )
            ]
        ),
    )


class PlatformStatusServiceTests(unittest.TestCase):
    def test_ready_schedulable_spot_node_makes_platform_available(self) -> None:
        core_v1_api = MagicMock()
        core_v1_api.list_node.return_value = client.V1NodeList(
            items=[make_node(ready=True)]
        )

        result = PlatformStatusService(core_v1_api=core_v1_api).get_status()

        self.assertEqual(result.status, PlatformAvailability.AVAILABLE)
        self.assertTrue(result.creation_allowed)
        self.assertIn("1", result.message)
        self.assertIsInstance(result.checked_at, datetime)

    def test_zero_ready_nodes_makes_platform_recovering(self) -> None:
        core_v1_api = MagicMock()
        core_v1_api.list_node.return_value = client.V1NodeList(
            items=[make_node(ready=False)]
        )

        result = PlatformStatusService(core_v1_api=core_v1_api).get_status()

        self.assertEqual(result.status, PlatformAvailability.RECOVERING)
        self.assertFalse(result.creation_allowed)

    def test_authentication_and_connection_failures_make_platform_unavailable(self) -> None:
        failures = (
            ApiException(status=401, reason="Unauthorized"),
            ConnectionError("DNS lookup failed"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                core_v1_api = MagicMock()
                core_v1_api.list_node.side_effect = failure

                result = PlatformStatusService(core_v1_api=core_v1_api).get_status()

                self.assertEqual(result.status, PlatformAvailability.UNAVAILABLE)
                self.assertFalse(result.creation_allowed)
                self.assertIn(str(failure), result.message)

    def test_no_schedule_taint_excluding_general_workloads_is_not_capacity(self) -> None:
        core_v1_api = MagicMock()
        core_v1_api.list_node.return_value = client.V1NodeList(
            items=[
                make_node(
                    ready=True,
                    taints=[
                        client.V1Taint(
                            key="workload.example.com/dedicated",
                            value="system",
                            effect="NoSchedule",
                        )
                    ],
                )
            ]
        )

        result = PlatformStatusService(core_v1_api=core_v1_api).get_status()

        self.assertEqual(result.status, PlatformAvailability.RECOVERING)
        self.assertFalse(result.creation_allowed)


if __name__ == "__main__":
    unittest.main()
