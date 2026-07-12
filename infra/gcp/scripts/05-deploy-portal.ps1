param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$Repository = "portal-demo",
  [string]$Tag = "latest",
  [string]$DbPassword = "change-me-before-demo"
)

$registry = "$Region-docker.pkg.dev/$ProjectId/$Repository"
$backendImage = "$registry/portal-backend:$Tag"
$frontendImage = "$registry/portal-frontend:$Tag"

kubectl apply -f infra/gcp/namespace.yaml
kubectl create secret generic portal-db-secret `
  --namespace portal-system `
  --from-literal=db-password=$DbPassword `
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k infra/gcp
kubectl -n portal-system set image deployment/portal-backend backend=$backendImage
kubectl -n portal-system set image deployment/portal-frontend frontend=$frontendImage
kubectl -n portal-system rollout status deployment/portal-mariadb --timeout=180s
kubectl -n portal-system rollout status deployment/portal-backend --timeout=180s
kubectl -n portal-system rollout status deployment/portal-frontend --timeout=180s

kubectl -n portal-system get ingress portal-demo
