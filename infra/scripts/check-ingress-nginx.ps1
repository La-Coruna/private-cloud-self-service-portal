param(
    [string]$HostName = "ingress-demo-staging.localtest.me",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

Write-Host "Checking ingress-nginx controller pods..."
kubectl get pods -n ingress-nginx

Write-Host "Checking IngressClass resources..."
kubectl get ingressclass

Write-Host "Host port check target:"
Write-Host "  curl http://${HostName}:$Port"
Write-Host "  browser http://${HostName}:$Port"

try {
    $response = Invoke-WebRequest -UseBasicParsing -Uri "http://${HostName}:$Port" -TimeoutSec 10
    Write-Host "HTTP status: $($response.StatusCode)"
    Write-Host $response.Content.Substring(0, [Math]::Min(200, $response.Content.Length))
} catch {
    Write-Host "HTTP check failed. Create an expose_external=true project for this host first."
    Write-Host $_.Exception.Message
}
