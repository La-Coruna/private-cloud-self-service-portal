[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2',
  [string]$Region = 'asia-northeast3',
  [string]$Repository = 'portal-demo',
  [string]$ClusterName = 'portal-demo-standard',
  [string]$Zone = 'asia-northeast3-a',
  [string]$ExpectedAccount = 'yougood260807@gmail.com'
)

$ErrorActionPreference = 'Stop'
$script:approvedProjectId = 'private-cloud-portal-demo-2'
$script:approvedRegion = 'asia-northeast3'
$script:approvedRepository = 'portal-demo'
$script:approvedClusterName = 'portal-demo-standard'
$script:approvedZone = 'asia-northeast3-a'
$script:approvedAccount = 'yougood260807@gmail.com'
$script:serviceName = 'portal-backend'
$script:serviceAccount = 'portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com'

function Assert-ApprovedIdentifiers {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredRegion,
    [Parameter(Mandatory = $true)][string]$RequiredRepository,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  if ($RequiredProjectId -cne $script:approvedProjectId) {
    throw 'The requested project is not the approved serverless migration project.'
  }
  if ($RequiredRegion -cne $script:approvedRegion) {
    throw 'The requested region is not the approved Seoul region.'
  }
  if ($RequiredRepository -cne $script:approvedRepository) {
    throw 'The requested Artifact Registry repository is not the discovered existing repository.'
  }
  if ($RequiredClusterName -cne $script:approvedClusterName) {
    throw 'The requested cluster is not the approved portal cluster.'
  }
  if ($RequiredZone -cne $script:approvedZone) {
    throw 'The requested zone is not the approved portal cluster zone.'
  }
  if ($RequiredAccount -cne $script:approvedAccount) {
    throw 'The requested deployment account is not the approved new account.'
  }
}

function Assert-Tooling {
  foreach ($command in @('gcloud', 'git', 'docker')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
      throw "Required command is unavailable: $command"
    }
  }
}

function Assert-GcloudContext {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  $activeProject = (& gcloud config get-value project 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $activeProject -cne $RequiredProjectId) {
    throw 'The active gcloud project does not match the approved project.'
  }

  $activeAccount = (& gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $activeAccount -cne $RequiredAccount) {
    throw 'The active gcloud account does not match the approved new deployment account.'
  }

  $resolvedProject = (& gcloud projects describe $RequiredProjectId --format='value(projectId)' 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $resolvedProject -cne $RequiredProjectId) {
    throw 'The approved GCP project is not accessible.'
  }
}

function Get-JsonFromCommand {
  param(
    [Parameter(Mandatory = $true)][scriptblock]$Command,
    [Parameter(Mandatory = $true)][string]$FailureMessage
  )

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $json = & $Command
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($exitCode -ne 0) {
    throw $FailureMessage
  }
  try {
    return (($json -join "`n") | ConvertFrom-Json)
  }
  catch {
    throw "$FailureMessage The command returned malformed JSON."
  }
}

function Assert-ArtifactRepository {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredRegion,
    [Parameter(Mandatory = $true)][string]$RequiredRepository
  )

  $repository = Get-JsonFromCommand -FailureMessage 'Could not describe the existing Artifact Registry repository.' -Command {
    & gcloud artifacts repositories describe $RequiredRepository `
      --location=$RequiredRegion --project=$RequiredProjectId --format=json 2>$null
  }
  $expectedName = "projects/$RequiredProjectId/locations/$RequiredRegion/repositories/$RequiredRepository"
  if ($repository.name -cne $expectedName) {
    throw 'Artifact Registry repository identity or location does not match the discovered existing repository.'
  }
  if ($repository.format -cne 'DOCKER') {
    throw 'The discovered Artifact Registry repository is not a Docker repository.'
  }
}

function Get-ValidatedGkeDnsEndpoint {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone
  )

  $cluster = Get-JsonFromCommand -FailureMessage 'Could not describe the approved GKE cluster.' -Command {
    & gcloud container clusters describe $RequiredClusterName `
      --zone=$RequiredZone --project=$RequiredProjectId --format=json 2>$null
  }
  if ($cluster.name -cne $RequiredClusterName -or $cluster.location -cne $RequiredZone) {
    throw 'GKE cluster metadata does not match the approved cluster and zone.'
  }
  if ($cluster.status -cne 'RUNNING') {
    throw "The approved GKE cluster is not RUNNING: $($cluster.status)"
  }

  $dns = $cluster.controlPlaneEndpointsConfig.dnsEndpointConfig
  $ip = $cluster.controlPlaneEndpointsConfig.ipEndpointsConfig
  if ($null -eq $dns -or $null -eq $ip) {
    throw 'GKE DNS or IP endpoint configuration is absent.'
  }
  if ($dns.allowExternalTraffic -isnot [bool] -or -not $dns.allowExternalTraffic) {
    throw 'The GKE DNS endpoint is not enabled for external traffic.'
  }
  if ($dns.enableK8sTokensViaDns -isnot [bool] -or $dns.enableK8sTokensViaDns) {
    throw 'Kubernetes tokens via DNS must remain disabled.'
  }
  if ($dns.enableK8sCertsViaDns -isnot [bool] -or $dns.enableK8sCertsViaDns) {
    throw 'Kubernetes certificates via DNS must remain disabled.'
  }
  if ($ip.enabled -isnot [bool] -or -not $ip.enabled -or
      $ip.enablePublicEndpoint -isnot [bool] -or -not $ip.enablePublicEndpoint) {
    throw 'The existing public IP endpoint must remain enabled for rollback.'
  }

  $hostname = [string]$dns.endpoint
  if ($hostname -cnotmatch '^[a-z0-9][a-z0-9.-]*\.gke\.goog$' -or
      $hostname.Contains(',') -or $hostname.Contains("`r") -or $hostname.Contains("`n")) {
    throw 'The discovered GKE DNS endpoint is missing or unsafe.'
  }
  return "https://$hostname"
}

function Get-ImmutableImageTag {
  $tag = (& git rev-parse --short HEAD 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $tag -cnotmatch '^[0-9a-f]{7,40}$') {
    throw 'Could not derive an immutable image tag from the current Git HEAD.'
  }
  return $tag
}

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)][scriptblock]$Command,
    [Parameter(Mandatory = $true)][string]$FailureMessage
  )

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    & $Command
    $exitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($exitCode -ne 0) {
    throw $FailureMessage
  }
}

function Get-VerifiedCloudRunResult {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredRegion
  )

  $service = Get-JsonFromCommand -FailureMessage 'Could not verify the deployed Cloud Run service.' -Command {
    & gcloud run services describe $script:serviceName `
      --project=$RequiredProjectId --region=$RequiredRegion --format=json 2>$null
  }
  if ($service.metadata.name -cne $script:serviceName) {
    throw 'Cloud Run service verification returned an unexpected service.'
  }
  if ($service.spec.template.spec.serviceAccountName -cne $script:serviceAccount) {
    throw 'Cloud Run service verification returned an unexpected runtime identity.'
  }
  if ([string]::IsNullOrWhiteSpace([string]$service.status.latestReadyRevisionName)) {
    throw 'Cloud Run did not report a ready revision.'
  }
  if ([string]$service.status.url -cnotmatch '^https://') {
    throw 'Cloud Run did not report an HTTPS service URL.'
  }
  return $service
}

function Invoke-CloudRunDeployment {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredRegion,
    [Parameter(Mandatory = $true)][string]$RequiredRepository,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  Assert-ApprovedIdentifiers -RequiredProjectId $RequiredProjectId `
    -RequiredRegion $RequiredRegion -RequiredRepository $RequiredRepository `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone `
    -RequiredAccount $RequiredAccount
  Assert-Tooling
  Assert-GcloudContext -RequiredProjectId $RequiredProjectId -RequiredAccount $RequiredAccount
  Assert-ArtifactRepository -RequiredProjectId $RequiredProjectId `
    -RequiredRegion $RequiredRegion -RequiredRepository $RequiredRepository
  $gkeDnsEndpoint = Get-ValidatedGkeDnsEndpoint -RequiredProjectId $RequiredProjectId `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone
  $tag = Get-ImmutableImageTag

  $registry = "$RequiredRegion-docker.pkg.dev"
  $image = "$registry/$RequiredProjectId/$RequiredRepository/$($script:serviceName):$tag"

  Invoke-CheckedCommand -FailureMessage 'Could not configure Docker authentication for Artifact Registry.' -Command {
    & gcloud auth configure-docker $registry --quiet | Out-Null
  }
  Invoke-CheckedCommand -FailureMessage 'Cloud Run container image build failed.' -Command {
    & docker build --file backend/Dockerfile --tag $image backend
  }
  Invoke-CheckedCommand -FailureMessage 'Cloud Run container image push failed.' -Command {
    & docker push $image
  }

  $environment = @(
    'APP_ENV=production',
    'REPOSITORY_BACKEND=firestore',
    "FIRESTORE_PROJECT_ID=$RequiredProjectId",
    'FIRESTORE_DATABASE=(default)',
    'KUBE_AUTH_MODE=gke',
    "GKE_CLUSTER_LOCATION=$RequiredZone",
    "GKE_CLUSTER_NAME=$RequiredClusterName",
    "GKE_DNS_ENDPOINT=$gkeDnsEndpoint",
    'DEMO_MODE=true',
    'DEMO_MAX_PROJECTS=3',
    'DEMO_MAX_REPLICAS=1',
    'DEMO_NAMESPACE_PREFIX=demo-',
    'INGRESS_BASE_DOMAIN=apps.la-coruna.xyz',
    'APP_INGRESS_CLASS_NAME=nginx'
  ) -join ','

  Invoke-CheckedCommand -FailureMessage 'Cloud Run deployment failed.' -Command {
    & gcloud run deploy $script:serviceName `
      --project=$RequiredProjectId `
      --region=$RequiredRegion `
      --image=$image `
      --service-account=$script:serviceAccount `
      --allow-unauthenticated `
      --min=0 `
      --max=2 `
      --cpu=1 `
      --memory=512Mi `
      --concurrency=20 `
      --timeout=60 `
      --set-env-vars=$environment `
      --quiet | Out-Null
  }

  $service = Get-VerifiedCloudRunResult -RequiredProjectId $RequiredProjectId `
    -RequiredRegion $RequiredRegion
  Write-Output "imageTag=$tag"
  Write-Output "revision=$($service.status.latestReadyRevisionName)"
  Write-Output "url=$($service.status.url)"
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-CloudRunDeployment -RequiredProjectId $ProjectId `
    -RequiredRegion $Region -RequiredRepository $Repository `
    -RequiredClusterName $ClusterName -RequiredZone $Zone `
    -RequiredAccount $ExpectedAccount
}
