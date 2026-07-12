param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$ClusterName = "portal-demo-autopilot"
)

Write-Host "This will delete the GKE Autopilot cluster '$ClusterName' in project '$ProjectId' and region '$Region'."
$confirm = Read-Host "Type DELETE to continue"
if ($confirm -ne "DELETE") {
  Write-Host "Cleanup cancelled."
  exit 0
}

kubectl delete -k infra/gcp --ignore-not-found=true

gcloud container clusters delete $ClusterName `
  --project $ProjectId `
  --region $Region `
  --quiet
