from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.config_exception import ConfigException

from app.config import get_settings


def check_kubernetes_connection() -> dict:
    settings = get_settings()

    try:
        config.load_kube_config(context=settings.kube_context)
        namespaces = client.CoreV1Api().list_namespace()
        namespace_names = [item.metadata.name for item in namespaces.items]

        return {
            "status": "ok",
            "context": settings.kube_context,
            "namespace_count": len(namespace_names),
            "namespaces": namespace_names,
        }
    except (ConfigException, ApiException, Exception) as exc:
        return {"status": "error", "message": str(exc)}
