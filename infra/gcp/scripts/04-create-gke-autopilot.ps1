param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$ClusterName = "portal-demo-autopilot"
)

gcloud container clusters create-auto $ClusterName `
  --project $ProjectId `
  --region $Region `
  --release-channel regular

gcloud container clusters get-credentials $ClusterName --project $ProjectId --region $Region
