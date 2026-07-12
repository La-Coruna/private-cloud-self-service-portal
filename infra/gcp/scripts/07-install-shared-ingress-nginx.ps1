param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$ClusterName = "portal-demo",
  [string]$Namespace = "ingress-nginx",
  [string]$ManifestUrl = "https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.13.3/deploy/static/provider/cloud/deploy.yaml"
)

$ErrorActionPreference = "Stop"

gcloud container clusters get-credentials $ClusterName --project $ProjectId --region $Region

$helm = Get-Command helm -ErrorAction SilentlyContinue
if ($helm) {
  helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
  helm repo update
  helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx `
    --namespace $Namespace `
    --create-namespace `
    --set controller.service.type=LoadBalancer `
    --set controller.ingressClassResource.name=nginx `
    --set controller.ingressClassResource.controllerValue=k8s.io/ingress-nginx
} else {
  Write-Host "Helm was not found. Installing ingress-nginx from pinned cloud manifest:"
  Write-Host $ManifestUrl
  kubectl apply -f $ManifestUrl
}

kubectl rollout status deployment/ingress-nginx-controller -n $Namespace --timeout=300s
kubectl get svc -n $Namespace
kubectl get ingressclass
