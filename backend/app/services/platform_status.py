from dataclasses import dataclass
from datetime import datetime

from kubernetes import client

from app.config import Settings, get_settings
from app.domain import PlatformAvailability, utc_now
from app.k8s_auth import build_api_client


@dataclass(frozen=True, slots=True)
class PlatformStatus:
    status: PlatformAvailability
    message: str
    creation_allowed: bool
    checked_at: datetime


def _node_is_ready(node: client.V1Node) -> bool:
    conditions = getattr(getattr(node, "status", None), "conditions", None) or []
    return any(
        condition.type == "Ready" and condition.status == "True"
        for condition in conditions
    )


def _node_accepts_general_workloads(node: client.V1Node) -> bool:
    spec = getattr(node, "spec", None)
    if spec is None or getattr(spec, "unschedulable", False):
        return False
    taints = getattr(spec, "taints", None) or []
    return not any(taint.effect == "NoSchedule" for taint in taints)


def _is_usable_node(node: client.V1Node) -> bool:
    return _node_is_ready(node) and _node_accepts_general_workloads(node)


class PlatformStatusService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        api_client: client.ApiClient | None = None,
        core_v1_api: client.CoreV1Api | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._api_client = api_client
        self._core_v1_api = core_v1_api

    def _get_core_v1_api(self) -> client.CoreV1Api:
        if self._core_v1_api is not None:
            return self._core_v1_api
        if self._api_client is None:
            self._api_client = build_api_client(self._settings)
        self._core_v1_api = client.CoreV1Api(api_client=self._api_client)
        return self._core_v1_api

    def get_status(self) -> PlatformStatus:
        checked_at = utc_now()
        try:
            nodes = self._get_core_v1_api().list_node()
        except Exception as exc:
            return PlatformStatus(
                status=PlatformAvailability.UNAVAILABLE,
                message=f"Kubernetes API connection failed: {exc}",
                creation_allowed=False,
                checked_at=checked_at,
            )

        usable_node_count = sum(
            1 for node in (getattr(nodes, "items", None) or []) if _is_usable_node(node)
        )
        if usable_node_count:
            return PlatformStatus(
                status=PlatformAvailability.AVAILABLE,
                message=f"GKE has {usable_node_count} Ready schedulable node(s)",
                creation_allowed=True,
                checked_at=checked_at,
            )
        return PlatformStatus(
            status=PlatformAvailability.RECOVERING,
            message="GKE is reachable but has no Ready schedulable nodes",
            creation_allowed=False,
            checked_at=checked_at,
        )
