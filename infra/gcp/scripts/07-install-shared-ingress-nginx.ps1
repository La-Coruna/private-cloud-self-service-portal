param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectId,

  [string]$Region = "asia-northeast3",

  [string]$Zone = "asia-northeast3-a",

  [string]$ClusterName = "portal-demo-standard",

  [string]$ControllerVersion = "controller-v1.13.3"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Command,

    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,

    [Parameter(Mandatory = $true)]
    [string]$FailureMessage
  )

  Write-Host ""
  Write-Host "> $Command $($Arguments -join ' ')" -ForegroundColor Cyan

  & $Command @Arguments

  if ($LASTEXITCODE -ne 0) {
    throw "$FailureMessage (exit code: $LASTEXITCODE)"
  }
}

Write-Host "Installing shared ingress-nginx controller..." -ForegroundColor Green
Write-Host "Project : $ProjectId"
Write-Host "Cluster : $ClusterName"
Write-Host "Zone    : $Zone"
Write-Host "Region  : $Region"

Invoke-Checked `
  -Command "gcloud" `
  -Arguments @(
    "config", "set", "project", $ProjectId
  ) `
  -FailureMessage "Failed to set gcloud project"

# This project uses a zonal GKE Standard cluster.
# Use --zone instead of --region to avoid:
# "Could not find [cluster] in [asia-northeast3]. Did you mean ... in [asia-northeast3-a]?"
Invoke-Checked `
  -Command "gcloud" `
  -Arguments @(
    "container", "clusters", "get-credentials", $ClusterName,
    "--project", $ProjectId,
    "--zone", $Zone
  ) `
  -FailureMessage "Failed to configure kubectl credentials"

Write-Host ""
Write-Host "Current kubectl context:" -ForegroundColor Green
kubectl config current-context

if ($LASTEXITCODE -ne 0) {
  throw "Failed to read current kubectl context."
}

$manifestUrl = "https://raw.githubusercontent.com/kubernetes/ingress-nginx/$ControllerVersion/deploy/static/provider/cloud/deploy.yaml"

Write-Host ""
Write-Host "Applying ingress-nginx cloud manifest:" -ForegroundColor Green
Write-Host $manifestUrl

Invoke-Checked `
  -Command "kubectl" `
  -Arguments @(
    "apply", "-f", $manifestUrl
  ) `
  -FailureMessage "Failed to apply ingress-nginx manifest"

Invoke-Checked `
  -Command "kubectl" `
  -Arguments @(
    "rollout", "status",
    "deployment/ingress-nginx-controller",
    "-n", "ingress-nginx",
    "--timeout=300s"
  ) `
  -FailureMessage "ingress-nginx controller rollout failed"

Write-Host ""
Write-Host "ingress-nginx services:" -ForegroundColor Green
kubectl get svc -n ingress-nginx

if ($LASTEXITCODE -ne 0) {
  throw "Failed to list ingress-nginx services."
}

Write-Host ""
Write-Host "Ingress classes:" -ForegroundColor Green
kubectl get ingressclass

if ($LASTEXITCODE -ne 0) {
  throw "Failed to list ingress classes."
}

Write-Host ""
Write-Host "Shared ingress-nginx installation completed." -ForegroundColor Green
Write-Host "Wait until ingress-nginx-controller gets an EXTERNAL-IP before changing DNS." -ForegroundColor Yellow