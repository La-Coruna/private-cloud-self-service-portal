param(
  [Parameter(Mandatory=$true)][string]$ProjectId
)

$services = @(
  "container.googleapis.com",
  "artifactregistry.googleapis.com",
  "compute.googleapis.com"
)

gcloud config set project $ProjectId
foreach ($service in $services) {
  gcloud services enable $service --project $ProjectId
}
