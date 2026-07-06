from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.config_exception import ConfigException

from app.config import get_settings


MANAGED_BY = "self-service-portal"


def load_kube_config() -> None:
    settings = get_settings()
    config.load_kube_config(context=settings.kube_context)


def build_common_labels(project_id: int, service_name: str, environment: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/managed-by": MANAGED_BY,
        "app.kubernetes.io/name": service_name,
        "platform.io/environment": environment,
        "platform.io/project-id": str(project_id),
    }


def build_selector_labels(project_id: int, service_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": service_name,
        "platform.io/project-id": str(project_id),
    }


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


def _api_error_result(resource: str, exc: ApiException) -> dict:
    return {
        "status": "error",
        "resource": resource,
        "message": exc.reason,
        "detail": exc.body,
    }


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
                labels=build_common_labels(project_id, service_name, environment),
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


def create_deployment(
    *,
    namespace: str,
    project_id: int,
    service_name: str,
    environment: str,
    image: str,
    replicas: int,
    cpu_request: str,
    cpu_limit: str,
    memory_request: str,
    memory_limit: str,
) -> dict:
    try:
        load_kube_config()
        selector_labels = build_selector_labels(project_id, service_name)
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=service_name,
                namespace=namespace,
                labels=build_common_labels(project_id, service_name, environment),
            ),
            spec=client.V1DeploymentSpec(
                replicas=replicas,
                selector=client.V1LabelSelector(match_labels=selector_labels),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=selector_labels),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name=service_name,
                                image=image,
                                ports=[client.V1ContainerPort(container_port=80)],
                                resources=client.V1ResourceRequirements(
                                    requests={
                                        "cpu": cpu_request,
                                        "memory": memory_request,
                                    },
                                    limits={
                                        "cpu": cpu_limit,
                                        "memory": memory_limit,
                                    },
                                ),
                            )
                        ]
                    ),
                ),
            ),
        )
        client.AppsV1Api().create_namespaced_deployment(
            namespace=namespace,
            body=deployment,
        )
        return {"status": "created", "resource": "deployment", "name": service_name}
    except ApiException as exc:
        if exc.status == 409:
            return {
                "status": "already_exists",
                "resource": "deployment",
                "name": service_name,
            }
        return _api_error_result("deployment", exc)
    except Exception as exc:
        return {"status": "error", "resource": "deployment", "message": str(exc)}


def create_service(
    *,
    namespace: str,
    project_id: int,
    service_name: str,
    environment: str,
) -> dict:
    service_name_with_suffix = f"{service_name}-svc"
    try:
        load_kube_config()
        service = client.V1Service(
            metadata=client.V1ObjectMeta(
                name=service_name_with_suffix,
                namespace=namespace,
                labels=build_common_labels(project_id, service_name, environment),
            ),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector=build_selector_labels(project_id, service_name),
                ports=[
                    client.V1ServicePort(
                        name="http",
                        port=80,
                        target_port=80,
                        protocol="TCP",
                    )
                ],
            ),
        )
        client.CoreV1Api().create_namespaced_service(
            namespace=namespace,
            body=service,
        )
        return {
            "status": "created",
            "resource": "service",
            "name": service_name_with_suffix,
        }
    except ApiException as exc:
        if exc.status == 409:
            return {
                "status": "already_exists",
                "resource": "service",
                "name": service_name_with_suffix,
            }
        return _api_error_result("service", exc)
    except Exception as exc:
        return {"status": "error", "resource": "service", "message": str(exc)}


def _container_state(container_status) -> tuple[str, str | None, str | None]:
    state = container_status.state
    if getattr(state, "running", None) is not None:
        return "running", None, None
    if getattr(state, "waiting", None) is not None:
        waiting = state.waiting
        return "waiting", waiting.reason, waiting.message
    if getattr(state, "terminated", None) is not None:
        terminated = state.terminated
        return "terminated", terminated.reason, terminated.message
    return "unknown", None, None


def _format_container_status(container_status) -> dict:
    state, reason, message = _container_state(container_status)
    return {
        "name": container_status.name,
        "image": container_status.image,
        "ready": container_status.ready,
        "restart_count": container_status.restart_count,
        "state": state,
        "reason": reason,
        "message": message,
    }


def list_project_pods(namespace: str, project_id: int) -> list[dict]:
    try:
        load_kube_config()
        pods = client.CoreV1Api().list_namespaced_pod(
            namespace=namespace,
            label_selector=f"platform.io/project-id={project_id}",
        )
        results = []
        for pod in pods.items:
            start_time = pod.status.start_time.isoformat() if pod.status.start_time else None
            container_statuses = pod.status.container_statuses or []
            results.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "node_name": pod.spec.node_name,
                    "start_time": start_time,
                    "containers": [
                        _format_container_status(status)
                        for status in container_statuses
                    ],
                }
            )
        return results
    except ApiException as exc:
        raise RuntimeError(f"Failed to list pods: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
