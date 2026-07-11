# Local Ingress Access

This project can create Kubernetes Ingress resources for projects where
`expose_external=true`. The Ingress object is only a routing rule. A local
cluster also needs an Ingress Controller and host port mapping before a browser
or `curl` can reach the workload.

## Request Flow

```text
browser or curl
-> http://<service>-<environment>.localtest.me:8080
-> kind control-plane hostPort 8080
-> ingress-nginx controller
-> Ingress rule
-> ClusterIP Service
-> nginx Pod
```

## Why Port Mapping Is Needed

kind runs Kubernetes nodes as Docker containers. The Ingress Controller listens
inside the kind node, so the host machine needs explicit port mappings:

- host `8080` -> kind node container `80`
- host `8443` -> kind node container `443`

These mappings are defined in `infra/kind/kind-config.yaml`. They only apply
when the kind cluster is created. If the cluster already exists without the
mappings, delete and recreate it.

## Why localtest.me Is Used

`localtest.me` resolves to `127.0.0.1`, including subdomains. That lets the
portal generate useful local hostnames such as:

```text
browser-demo-staging.localtest.me
```

No hosts file edit is needed.

## Create The Local Cluster

PowerShell:

```powershell
.\infra\scripts\create-kind-cluster.ps1
```

If the cluster already exists but was created before port mappings were added,
recreate it:

```powershell
.\infra\scripts\delete-kind-cluster.ps1
.\infra\scripts\create-kind-cluster.ps1
```

## Install ingress-nginx

PowerShell:

```powershell
.\infra\scripts\install-ingress-nginx.ps1
```

The script applies the official ingress-nginx manifest for kind and waits for
the controller Pod to become ready.

Check the controller:

```powershell
.\infra\scripts\check-ingress-nginx.ps1
```

## Create An Exposed Project

```powershell
$body = @{
  service_name = "browser-demo"
  environment = "staging"
  image = "nginx:latest"
  replicas = 1
  cpu_request = "100m"
  cpu_limit = "500m"
  memory_request = "128Mi"
  memory_limit = "512Mi"
  expose_external = $true
} | ConvertTo-Json

$project = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/projects" `
  -ContentType "application/json" `
  -Body $body

$project
```

Expected `ingress_host`:

```text
browser-demo-staging.localtest.me
```

## Verify Kubernetes Resources

```powershell
kubectl get ingress -n browser-demo-staging
kubectl describe ingress browser-demo-ingress -n browser-demo-staging
kubectl get all -n browser-demo-staging
```

## Verify Browser Or curl Access

```powershell
curl.exe http://browser-demo-staging.localtest.me:8080
```

Or open:

```text
http://browser-demo-staging.localtest.me:8080
```

The default nginx welcome page or any HTTP 200 response confirms the local
Ingress path is working.


## Temporary Port Forward Fallback

If the current kind cluster was created before `extraPortMappings` were added
and you do not want to recreate it yet, you can still verify Ingress routing
with a temporary port-forward:

```powershell
kubectl port-forward `
  -n ingress-nginx `
  service/ingress-nginx-controller `
  8080:80
```

Keep that command running, then test the generated host:

```powershell
curl.exe --noproxy * http://browser-demo-staging.localtest.me:8080
```

This proves ingress-nginx, the Ingress rule, Service, and Pod routing. Recreate
the kind cluster with `infra/kind/kind-config.yaml` when you want the same URL
to work without a port-forward process.

## Troubleshooting

If the browser cannot connect:

```powershell
kubectl get pods -n ingress-nginx
kubectl get ingressclass
kubectl get ingress -n browser-demo-staging
kubectl describe ingress browser-demo-ingress -n browser-demo-staging
kubectl get endpoints -n browser-demo-staging
```

Common causes:

- The kind cluster was created before `extraPortMappings` were added.
- ingress-nginx is not installed or its controller Pod is not ready.
- The project was created with `expose_external=false`.
- The Pod is not ready, so the Service has no healthy endpoint.
- The wrong host or port was used. Local access uses port `8080`.

## Cleanup

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri "http://127.0.0.1:8000/api/projects/$($project.id)"
```

Confirm cleanup:

```powershell
kubectl get namespace browser-demo-staging
```

