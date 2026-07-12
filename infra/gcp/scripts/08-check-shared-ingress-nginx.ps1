param(
  [string]$Namespace = "ingress-nginx",
  [string]$WildcardHost = "demo-shared-ingress-staging.apps.la-coruna.xyz"
)

$ErrorActionPreference = "Stop"

kubectl get pods -n $Namespace
kubectl get svc -n $Namespace
kubectl get ingressclass

$externalIp = kubectl get svc ingress-nginx-controller -n $Namespace -o jsonpath="{.status.loadBalancer.ingress[0].ip}"
if (-not $externalIp) {
  Write-Host "ingress-nginx-controller does not have an External IP yet."
  exit 1
}

Write-Host "Shared ingress-nginx External IP: $externalIp"
Write-Host ""
Write-Host "Update Spaceship DNS when ready:"
Write-Host "  A *.apps -> $externalIp"
Write-Host ""
Write-Host "Before DNS propagation, test with:"
Write-Host "  curl.exe -I --resolve ${WildcardHost}:80:$externalIp http://${WildcardHost}/"
