import base64
from pathlib import Path
import tempfile

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
from kubernetes import client, config

from app.config import Settings


CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
CONTAINER_API_ROOT = "https://container.googleapis.com/v1"


def _refresh_credentials(credentials) -> None:
    if (
        getattr(credentials, "expired", False)
        or not getattr(credentials, "valid", False)
        or not getattr(credentials, "token", None)
    ):
        credentials.refresh(Request())


def _cluster_ca_path(cluster: dict) -> str:
    encoded_ca = cluster.get("masterAuth", {}).get("clusterCaCertificate")
    if not encoded_ca:
        raise ValueError("GKE cluster response did not include a cluster CA certificate")

    ca_file = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="gke-cluster-ca-",
        suffix=".crt",
        delete=False,
    )
    with ca_file:
        ca_file.write(base64.b64decode(encoded_ca, validate=True))
    return str(Path(ca_file.name))


def _build_gke_api_client(settings: Settings) -> client.ApiClient:
    credentials, adc_project_id = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    _refresh_credentials(credentials)

    project_id = settings.firestore_project_id or adc_project_id
    if not project_id:
        raise ValueError("A Google Cloud project ID is required for GKE authentication")
    if not settings.gke_cluster_location or not settings.gke_cluster_name:
        raise ValueError("GKE cluster location and name are required")
    if not settings.gke_dns_endpoint:
        raise ValueError("A GKE DNS endpoint is required")

    cluster_url = (
        f"{CONTAINER_API_ROOT}/projects/{project_id}/locations/"
        f"{settings.gke_cluster_location}/clusters/{settings.gke_cluster_name}"
    )
    session = AuthorizedSession(credentials)
    response = session.get(cluster_url)
    response.raise_for_status()

    configuration = client.Configuration()
    configuration.host = settings.gke_dns_endpoint
    configuration.ssl_ca_cert = _cluster_ca_path(response.json())
    configuration.api_key["authorization"] = credentials.token
    configuration.api_key_prefix["authorization"] = "Bearer"

    def refresh_api_key(config_to_refresh: client.Configuration) -> None:
        _refresh_credentials(credentials)
        config_to_refresh.api_key["authorization"] = credentials.token

    configuration.refresh_api_key_hook = refresh_api_key
    return client.ApiClient(configuration=configuration)


def build_api_client(settings: Settings) -> client.ApiClient:
    if settings.kube_auth_mode == "local":
        config.load_kube_config(context=settings.kube_context)
        return client.ApiClient()
    return _build_gke_api_client(settings)
