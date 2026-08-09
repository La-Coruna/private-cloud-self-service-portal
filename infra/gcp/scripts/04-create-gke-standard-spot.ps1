param(
  [Parameter(Mandatory = $true)]
  [string]$ProjectId,

  [string]$Zone = "asia-northeast3-a",
  [string]$ClusterName = "portal-demo-standard",
  [string]$MachineType = "e2-medium",
  [int]$NumNodes = 1,
  [int]$DiskSizeGb = 30,
  [string]$DiskType = "pd-standard",
  [string]$ReleaseChannel = "regular"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Gcloud {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Arguments,

    [Parameter(Mandatory = $true)]
    [string]$FailureMessage
  )

  Write-Host ""
  Write-Host "> gcloud $($Arguments -join ' ')" -ForegroundColor Cyan

  & gcloud @Arguments

  if ($LASTEXITCODE -ne 0) {
    throw "$FailureMessage (exit code: $LASTEXITCODE)"
  }
}

function Test-ClusterExists {
  param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$Zone,

    [Parameter(Mandatory = $true)]
    [string]$ClusterName
  )

  Write-Host ""
  Write-Host "Checking whether cluster already exists..." -ForegroundColor Cyan

  $result = & gcloud container clusters list `
    --project $ProjectId `
    --zone $Zone `
    --filter "name=$ClusterName" `
    --format "value(name)"

  if ($LASTEXITCODE -ne 0) {
    throw "Failed to list GKE clusters. (exit code: $LASTEXITCODE)"
  }

  return ($result -eq $ClusterName)
}

Write-Host "Creating cost-optimized GKE Standard single-zone cluster with Spot VM..." -ForegroundColor Green
Write-Host "Project      : $ProjectId"
Write-Host "Zone         : $Zone"
Write-Host "Cluster      : $ClusterName"
Write-Host "Machine type : $MachineType"
Write-Host "Nodes        : $NumNodes"
Write-Host "Disk         : $DiskSizeGb GB / $DiskType"
Write-Host "Release      : $ReleaseChannel"

Invoke-Gcloud `
  -Arguments @(
    "config", "set", "project", $ProjectId
  ) `
  -FailureMessage "Failed to set gcloud project"

Invoke-Gcloud `
  -Arguments @(
    "services", "enable",
    "container.googleapis.com",
    "compute.googleapis.com",
    "artifactregistry.googleapis.com",
    "--project", $ProjectId
  ) `
  -FailureMessage "Failed to enable required GCP APIs"

$clusterExists = Test-ClusterExists `
  -ProjectId $ProjectId `
  -Zone $Zone `
  -ClusterName $ClusterName

if ($clusterExists) {
  Write-Host ""
  Write-Host "Cluster already exists. Skipping create step." -ForegroundColor Yellow
} else {
  Invoke-Gcloud `
    -Arguments @(
      "container", "clusters", "create", $ClusterName,
      "--project", $ProjectId,
      "--zone", $Zone,
      "--num-nodes", "$NumNodes",
      "--machine-type", $MachineType,
      "--spot",
      "--disk-size", "$DiskSizeGb",
      "--disk-type", $DiskType,
      "--enable-ip-alias",
      "--release-channel", $ReleaseChannel,
      "--enable-autorepair",
      "--enable-autoupgrade",
      "--no-enable-managed-prometheus",
      "--monitoring", "SYSTEM",
      "--quiet"
    ) `
    -FailureMessage "Failed to create GKE Standard Spot cluster"
}

Invoke-Gcloud `
  -Arguments @(
    "container", "clusters", "get-credentials", $ClusterName,
    "--project", $ProjectId,
    "--zone", $Zone
  ) `
  -FailureMessage "Failed to configure kubectl credentials"

Write-Host ""
Write-Host "Verifying cluster and node status..." -ForegroundColor Green

kubectl config current-context
if ($LASTEXITCODE -ne 0) {
  throw "Failed to read current kubectl context."
}

kubectl get nodes -o wide
if ($LASTEXITCODE -ne 0) {
  throw "Failed to get GKE nodes."
}

kubectl get nodes -L cloud.google.com/gke-spot
if ($LASTEXITCODE -ne 0) {
  throw "Failed to verify Spot node label."
}

Write-Host ""
Write-Host "Checking Managed Prometheus setting..." -ForegroundColor Green

$prometheusEnabled = & gcloud container clusters describe $ClusterName `
  --project $ProjectId `
  --zone $Zone `
  --format "value(monitoringConfig.managedPrometheusConfig.enabled)"

if ($LASTEXITCODE -ne 0) {
  throw "Failed to check Managed Prometheus setting."
}

Write-Host "Managed Prometheus enabled: $prometheusEnabled"

if ($prometheusEnabled -eq "True" -or $prometheusEnabled -eq "true") {
  Write-Host "Warning: Managed Prometheus appears to be enabled. Consider disabling it to reduce cost." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "GKE Standard Spot cluster is ready and kubectl is configured." -ForegroundColor Green
Write-Host "Next step: install shared ingress-nginx, then deploy portal-system." -ForegroundColor Green