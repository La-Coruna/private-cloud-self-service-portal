from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.config_exception import ConfigException

from app.config import get_settings


def load_kube_config() -> None:
    settings = get_settings()
    config.load_kube_config(context=settings.kube_context)


def check_kubernetes_connection() -> dict:
    settings = get_settings()

    try:
        load_kube_config()
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


def create_namespace(
    namespace: str,
    project_id: int,
    service_name: str,
    environment: str,
) -> dict:
    try:
        load_kube_config()
        body = client.V1Namespace(
            metadata=client.V1ObjectMeta(
                name=namespace,
                labels={
                    "app.kubernetes.io/managed-by": "self-service-portal",
                    "app.kubernetes.io/name": service_name,
                    "platform.io/environment": environment,
                    "platform.io/project-id": str(project_id),
                },
            )
        )
        client.CoreV1Api().create_namespace(body)
        return {"status": "created", "namespace": namespace}
    except ApiException as exc:
        if exc.status == 409:
            return {"status": "already_exists", "namespace": namespace}
        return {
            "status": "error",
            "message": exc.reason,
            "detail": exc.body,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}
