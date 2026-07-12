param(
  [Parameter(Mandatory=$true)][string]$ProjectId,
  [string]$Region = "asia-northeast3",
  [string]$Repository = "portal-demo",
  [string]$Tag = "latest",
  [string]$ApiBaseUrl = "/api"
)

$registry = "$Region-docker.pkg.dev/$ProjectId/$Repository"
$backendImage = "$registry/portal-backend:$Tag"
$frontendImage = "$registry/portal-frontend:$Tag"

gcloud auth configure-docker "$Region-docker.pkg.dev" --quiet

docker build -f backend/Dockerfile -t $backendImage backend
docker build -f frontend/Dockerfile --build-arg VITE_API_BASE_URL=$ApiBaseUrl -t $frontendImage frontend

docker push $backendImage
docker push $frontendImage

Write-Host "Backend image: $backendImage"
Write-Host "Frontend image: $frontendImage"
