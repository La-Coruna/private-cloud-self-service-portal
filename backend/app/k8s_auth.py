import atexit
import base64
import os
from pathlib import Path
import tempfile
from threading import Lock

import google.auth
from google.auth.transport.requests import AuthorizedSession, Request
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from app.config import Settings


CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
CONTAINER_API_ROOT = "https://container.googleapis.com/v1"
CONTAINER_API_TIMEOUT = (3.05, 10.0)
_cached_api_client: client.ApiClient | None = None
_cached_settings: Settings | None = None
_cached_ca_path: Path | None = None
_cache_lock = Lock()


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

    ca_bytes = base64.b64decode(encoded_ca, validate=True)
    file_descriptor, ca_name = tempfile.mkstemp(
        prefix="gke-cluster-ca-",
        suffix=".crt",
    )
    ca_path = Path(ca_name)
    try:
        os.chmod(ca_path, 0o600)
        with os.fdopen(file_descriptor, "wb") as ca_file:
            file_descriptor = -1
            ca_file.write(ca_bytes)
    except Exception:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        ca_path.unlink(missing_ok=True)
        raise
    return str(ca_path)


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
    try:
        response = session.get(cluster_url, timeout=CONTAINER_API_TIMEOUT)
        response.raise_for_status()
        cluster = response.json()
    finally:
        session.close()

    configuration = client.Configuration()
    configuration.host = settings.gke_dns_endpoint
    configuration.api_key["authorization"] = credentials.token
    configuration.api_key_prefix["authorization"] = "Bearer"

    def refresh_api_key(config_to_refresh: client.Configuration) -> None:
        _refresh_credentials(credentials)
        config_to_refresh.api_key["authorization"] = credentials.token

    configuration.refresh_api_key_hook = refresh_api_key
    return client.ApiClient(configuration=configuration)


def _close_client_and_ca(
    api_client: client.ApiClient | None,
    ca_path: Path | None,
) -> None:
    if api_client is not None:
        api_client.close()
    if ca_path is not None:
        ca_path.unlink(missing_ok=True)


def close_cached_api_client() -> None:
    global _cached_api_client, _cached_settings, _cached_ca_path
    with _cache_lock:
        api_client = _cached_api_client
        ca_path = _cached_ca_path
        _cached_api_client = None
        _cached_settings = None
        _cached_ca_path = None
    _close_client_and_ca(api_client, ca_path)


def build_api_client(settings: Settings) -> client.ApiClient:
    global _cached_api_client, _cached_settings, _cached_ca_path
    if settings.kube_auth_mode == "local":
        if not settings.kube_context:
            raise ConfigException("Local mode requires a named kube context")
        config.load_kube_config(context=settings.kube_context)
        return client.ApiClient()

    with _cache_lock:
        if _cached_api_client is not None and _cached_settings is settings:
            return _cached_api_client
        next_api_client = _build_gke_api_client(settings)
        ssl_ca_cert = next_api_client.configuration.ssl_ca_cert
        next_ca_path = Path(ssl_ca_cert) if ssl_ca_cert else None
        previous_api_client = _cached_api_client
        previous_ca_path = _cached_ca_path
        _cached_api_client = next_api_client
        _cached_settings = settings
        _cached_ca_path = next_ca_path

    _close_client_and_ca(previous_api_client, previous_ca_path)
    return next_api_client


atexit.register(close_cached_api_client)
