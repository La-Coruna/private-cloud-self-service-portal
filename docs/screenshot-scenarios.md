# Screenshot Scenarios

Use these scenarios to collect portfolio screenshots that show the project as a complete platform workflow, not just a CRUD app.

## 1. Project list

Goal:

- Show the main dashboard entry point.
- Capture service name, environment, image, namespace, status, expose external, ingress host, and created time.

URL:

```text
http://127.0.0.1:5173/projects
```

Best shot:

- Include a mix of `RUNNING`, `FAILED`, and `DELETED` projects if possible.

## 2. Project creation form

Goal:

- Show that developers can request a service without writing YAML.

Example values:

```text
service_name: portfolio-demo
environment: staging
image: nginx:latest
replicas: 1
cpu_request: 100m
cpu_limit: 500m
memory_request: 128Mi
memory_limit: 512Mi
expose_external: true
```

Capture points:

- Environment selector.
- Resource request/limit inputs.
- `expose_external` control.

## 3. expose_external=true project creation

Goal:

- Show that the external exposure option creates an Ingress host.

Verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/projects/<id>
```

Capture points:

- Request form with `expose_external=true`.
- Detail page after creation.
- Ingress host field.

## 4. Ingress host display

Goal:

- Show a generated host such as `portfolio-demo-staging.localtest.me`.

Verify:

```powershell
kubectl get ingress -n portfolio-demo-staging
curl.exe http://portfolio-demo-staging.localtest.me:8080
```

Capture points:

- Detail screen Ingress value.
- Optional terminal proof with HTTP response.

## 5. Pod Running status

Goal:

- Show that the platform can inspect live Kubernetes Pod state.

Capture points:

- Pod name.
- phase `Running`.
- container state `running`.
- node name.

## 6. ImagePullBackOff failure state

Goal:

- Show operational diagnosis for a failed workload.

Example project:

```text
service_name: bad-image
environment: staging
image: nginx-not-exist-portfolio:latest
replicas: 1
expose_external: false
```

Verify:

```powershell
kubectl get pods -n bad-image-staging
```

Capture points:

- Pod table with container reason `ImagePullBackOff`.
- Kubernetes Event table with `Failed` or `BackOff` messages.

## 7. FAILED status after sync-status

Goal:

- Show that the system corrects DB status from real Kubernetes state.

Steps:

1. Open the bad image project detail page.
2. Click `Status refresh`.
3. Capture the status badge after it becomes `FAILED`.

API verification:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/projects/<id>/sync-status
```

Capture points:

- `FAILED` status badge.
- error message with waiting reason or latest Event message.

## 8. Audit Log timeline

Goal:

- Show traceability of platform actions.

Capture points:

- `PROJECT_CREATE_REQUESTED`
- `NAMESPACE_CREATED`
- `RESOURCE_QUOTA_CREATED`
- `DEPLOYMENT_CREATED`
- `SERVICE_CREATED`
- `INGRESS_CREATED`
- `PROJECT_STATUS_SYNCED`
- failure entries with status `FAILED`

## 9. DELETED status after deletion

Goal:

- Show cleanup automation and lifecycle completion.

Steps:

1. Click delete on the detail page.
2. Confirm deletion.
3. Return to the list.
4. Capture the project with status `DELETED`.

Verify:

```powershell
kubectl get ns <namespace>
Invoke-RestMethod http://127.0.0.1:8000/api/projects/<id>/audit-logs
```

Capture points:

- list row with `DELETED` badge.
- audit entries for Ingress, Service, Deployment, ResourceQuota, Namespace, and final project deletion.

## Captured Files

The portfolio screenshot set is stored in `docs/screenshots/`.

| File | Scenario |
| --- | --- |
| `docs/screenshots/01-project-list.png` | Project list with portfolio scenario rows |
| `docs/screenshots/02-create-project-form.png` | Filled project creation form for `portfolio-demo` |
| `docs/screenshots/03-create-external-project.png` | Created external project detail with Ingress host |
| `docs/screenshots/04-project-detail-running.png` | Running project detail overview |
| `docs/screenshots/05-pod-status-running.png` | Running Pod status panel |
| `docs/screenshots/06-kubernetes-events.png` | Kubernetes Event panel |
| `docs/screenshots/07-audit-log-timeline.png` | Audit Log timeline panel |
| `docs/screenshots/08-bad-image-created.png` | `broken-demo` created with invalid image |
| `docs/screenshots/09-imagepullbackoff-pod.png` | Pod/Event panel showing image pull failure |
| `docs/screenshots/10-sync-status-failed.png` | FAILED status after `sync-status` |
| `docs/screenshots/11-delete-project.png` | Project list after deletion flow |
| `docs/screenshots/12-kubectl-resources.png` | `kubectl` resource verification output |
