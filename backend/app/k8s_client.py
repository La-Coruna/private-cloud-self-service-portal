from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.config_exception import ConfigException

from app.config import get_settings


MANAGED_BY = "self-service-portal"
RESOURCE_QUOTA_NAME = "portal-resource-quota"
DEFAULT_RESOURCE_QUOTA_HARD = {
    "requests.cpu": "4",
    "requests.memory": "4Gi",
    "limits.cpu": "8",
    "limits.memory": "8Gi",
    "pods": "10",
}


def load_kube_config() -> None:
    settings = get_settings()
    if settings.kube_context:
        config.load_kube_config(context=settings.kube_context)
        return
    config.load_incluster_config()


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


def build_ingress_host(service_name: str, environment: str) -> str:
    return f"{service_name}-{environment}.localtest.me"


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


def _is_not_found(exc: ApiException) -> bool:
    return exc.status == 404


def _delete_success(resource: str, name: str) -> dict:
    return {
        "status": "deleted",
        "resource": resource,
        "name": name,
    }


def _delete_already_absent(resource: str, name: str) -> dict:
    return {
        "status": "not_found",
        "resource": resource,
        "name": name,
    }


def _delete_api_error_result(resource: str, name: str, exc: ApiException) -> dict:
    return {
        "status": "error",
        "resource": resource,
        "name": name,
        "message": exc.reason,
        "detail": exc.body,
    }


def _delete_error_result(resource: str, name: str, exc: Exception) -> dict:
    return {
        "status": "error",
        "resource": resource,
        "name": name,
        "message": str(exc),
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


def create_resource_quota(
    *,
    namespace: str,
    project_id: int,
    service_name: str,
    environment: str,
) -> dict:
    try:
        load_kube_config()
        resource_quota = client.V1ResourceQuota(
            api_version="v1",
            kind="ResourceQuota",
            metadata=client.V1ObjectMeta(
                name=RESOURCE_QUOTA_NAME,
                namespace=namespace,
                labels=build_common_labels(project_id, service_name, environment),
            ),
            spec=client.V1ResourceQuotaSpec(hard=DEFAULT_RESOURCE_QUOTA_HARD),
        )
        client.CoreV1Api().create_namespaced_resource_quota(
            namespace=namespace,
            body=resource_quota,
        )
        return {
            "status": "created",
            "resource": "resourcequota",
            "name": RESOURCE_QUOTA_NAME,
        }
    except ApiException as exc:
        if exc.status == 409:
            return {
                "status": "already_exists",
                "resource": "resourcequota",
                "name": RESOURCE_QUOTA_NAME,
            }
        return _api_error_result("resourcequota", exc)
    except Exception as exc:
        return {"status": "error", "resource": "resourcequota", "message": str(exc)}


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


def create_ingress(
    *,
    namespace: str,
    project_id: int,
    service_name: str,
    environment: str,
    host: str,
) -> dict:
    ingress_name = f"{service_name}-ingress"
    service_name_with_suffix = f"{service_name}-svc"
    try:
        load_kube_config()
        ingress = client.V1Ingress(
            api_version="networking.k8s.io/v1",
            kind="Ingress",
            metadata=client.V1ObjectMeta(
                name=ingress_name,
                namespace=namespace,
                labels=build_common_labels(project_id, service_name, environment),
            ),
            spec=client.V1IngressSpec(
                rules=[
                    client.V1IngressRule(
                        host=host,
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=service_name_with_suffix,
                                            port=client.V1ServiceBackendPort(number=80),
                                        )
                                    ),
                                )
                            ]
                        ),
                    )
                ]
            ),
        )
        client.NetworkingV1Api().create_namespaced_ingress(
            namespace=namespace,
            body=ingress,
        )
        return {"status": "created", "resource": "ingress", "name": ingress_name}
    except ApiException as exc:
        if exc.status == 409:
            return {
                "status": "already_exists",
                "resource": "ingress",
                "name": ingress_name,
            }
        return _api_error_result("ingress", exc)
    except Exception as exc:
        return {"status": "error", "resource": "ingress", "message": str(exc)}


def delete_ingress(namespace: str, service_name: str) -> dict:
    ingress_name = f"{service_name}-ingress"
    try:
        load_kube_config()
        client.NetworkingV1Api().delete_namespaced_ingress(
            name=ingress_name,
            namespace=namespace,
        )
        return _delete_success("ingress", ingress_name)
    except ApiException as exc:
        if _is_not_found(exc):
            return _delete_already_absent("ingress", ingress_name)
        return _delete_api_error_result("ingress", ingress_name, exc)
    except Exception as exc:
        return _delete_error_result("ingress", ingress_name, exc)


def delete_service(namespace: str, service_name: str) -> dict:
    service_resource_name = f"{service_name}-svc"
    try:
        load_kube_config()
        client.CoreV1Api().delete_namespaced_service(
            name=service_resource_name,
            namespace=namespace,
        )
        return _delete_success("service", service_resource_name)
    except ApiException as exc:
        if _is_not_found(exc):
            return _delete_already_absent("service", service_resource_name)
        return _delete_api_error_result("service", service_resource_name, exc)
    except Exception as exc:
        return _delete_error_result("service", service_resource_name, exc)


def delete_deployment(namespace: str, service_name: str) -> dict:
    try:
        load_kube_config()
        client.AppsV1Api().delete_namespaced_deployment(
            name=service_name,
            namespace=namespace,
        )
        return _delete_success("deployment", service_name)
    except ApiException as exc:
        if _is_not_found(exc):
            return _delete_already_absent("deployment", service_name)
        return _delete_api_error_result("deployment", service_name, exc)
    except Exception as exc:
        return _delete_error_result("deployment", service_name, exc)


def delete_resource_quota(namespace: str) -> dict:
    try:
        load_kube_config()
        client.CoreV1Api().delete_namespaced_resource_quota(
            name=RESOURCE_QUOTA_NAME,
            namespace=namespace,
        )
        return _delete_success("resourcequota", RESOURCE_QUOTA_NAME)
    except ApiException as exc:
        if _is_not_found(exc):
            return _delete_already_absent("resourcequota", RESOURCE_QUOTA_NAME)
        return _delete_api_error_result("resourcequota", RESOURCE_QUOTA_NAME, exc)
    except Exception as exc:
        return _delete_error_result("resourcequota", RESOURCE_QUOTA_NAME, exc)


def delete_namespace(namespace: str) -> dict:
    try:
        load_kube_config()
        client.CoreV1Api().delete_namespace(name=namespace)
        return _delete_success("namespace", namespace)
    except ApiException as exc:
        if _is_not_found(exc):
            return _delete_already_absent("namespace", namespace)
        return _delete_api_error_result("namespace", namespace, exc)
    except Exception as exc:
        return _delete_error_result("namespace", namespace, exc)


def delete_project_resources(namespace: str, service_name: str) -> list[dict]:
    return [
        delete_ingress(namespace=namespace, service_name=service_name),
        delete_service(namespace=namespace, service_name=service_name),
        delete_deployment(namespace=namespace, service_name=service_name),
        delete_resource_quota(namespace=namespace),
        delete_namespace(namespace=namespace),
    ]


def _to_iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _event_sort_timestamp(event) -> float:
    metadata = getattr(event, "metadata", None)
    for value in (
        getattr(event, "last_timestamp", None),
        getattr(event, "event_time", None),
        getattr(metadata, "creation_timestamp", None),
        getattr(event, "first_timestamp", None),
    ):
        if value is not None:
            return value.timestamp()
    return float("-inf")


def _is_project_event(event, managed_object_names: set[str], service_name: str) -> bool:
    involved_object = getattr(event, "involved_object", None)
    object_name = getattr(involved_object, "name", None)
    if object_name is None:
        return False
    return object_name in managed_object_names or object_name.startswith(f"{service_name}-")


def _format_event(event) -> dict:
    involved_object = getattr(event, "involved_object", None)
    source = getattr(event, "source", None)
    return {
        "type": getattr(event, "type", None),
        "reason": getattr(event, "reason", None),
        "message": getattr(event, "message", None),
        "count": getattr(event, "count", None),
        "involved_object_kind": getattr(involved_object, "kind", None),
        "involved_object_name": getattr(involved_object, "name", None),
        "first_timestamp": _to_iso(getattr(event, "first_timestamp", None)),
        "last_timestamp": _to_iso(getattr(event, "last_timestamp", None)),
        "event_time": _to_iso(getattr(event, "event_time", None)),
        "source_component": getattr(source, "component", None),
    }

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


def list_project_events(
    namespace: str,
    project_id: int,
    service_name: str,
    limit: int = 50,
) -> list[dict]:
    try:
        load_kube_config()
        core_v1 = client.CoreV1Api()
        pods = core_v1.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"platform.io/project-id={project_id}",
        )
        managed_object_names = {
            service_name,
            f"{service_name}-svc",
            f"{service_name}-ingress",
        }
        managed_object_names.update(
            pod.metadata.name
            for pod in pods.items
            if getattr(pod.metadata, "name", None) is not None
        )

        events = core_v1.list_namespaced_event(namespace=namespace)
        project_events = [
            event
            for event in events.items
            if _is_project_event(event, managed_object_names, service_name)
        ]
        project_events.sort(key=_event_sort_timestamp, reverse=True)
        return [_format_event(event) for event in project_events[:limit]]
    except ApiException as exc:
        raise RuntimeError(f"Kubernetes API error: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
