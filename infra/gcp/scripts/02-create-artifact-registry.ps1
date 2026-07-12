param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$Repository = "portal-demo"
)

gcloud artifacts repositories create $Repository `
  --project $ProjectId `
  --repository-format=docker `
  --location=$Region `
  --description="Private cloud self-service portal demo images" `
  --quiet
