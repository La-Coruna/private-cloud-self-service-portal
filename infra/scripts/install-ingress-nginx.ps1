param(
    [string]$ClusterName = "portal-dev",
    [string]$ManifestUrl = "https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml"
)

$ErrorActionPreference = "Stop"

Write-Host "Installing ingress-nginx for kind cluster '$ClusterName'..."
kubectl config use-context "kind-$ClusterName"
kubectl apply -f $ManifestUrl

Write-Host "Waiting for ingress-nginx controller to become ready..."
kubectl wait --namespace ingress-nginx `
    --for=condition=ready pod `
    --selector=app.kubernetes.io/component=controller `
    --timeout=180s

kubectl get pods -n ingress-nginx
kubectl get ingressclass
