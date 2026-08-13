[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2'
)

$ErrorActionPreference = 'Stop'

$apis = @(
  'run.googleapis.com',
  'firestore.googleapis.com',
  'firebase.googleapis.com',
  'firebasehosting.googleapis.com',
  'artifactregistry.googleapis.com',
  'container.googleapis.com',
  'iam.googleapis.com'
)

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw 'gcloud CLI is unavailable.'
}

$resolvedProject = (& gcloud projects describe $ProjectId --format='value(projectId)').Trim()
if ($LASTEXITCODE -ne 0 -or $resolvedProject -ne $ProjectId) {
  throw "Cannot access the requested GCP project: $ProjectId"
}

gcloud services enable @apis --project $ProjectId
if ($LASTEXITCODE -ne 0) {
  throw 'One or more approved serverless APIs could not be enabled.'
}

$enabledApis = @(
  gcloud services list --enabled --project $ProjectId `
    --filter="config.name:($($apis -join ' OR '))" `
    --format='value(config.name)'
)
if ($LASTEXITCODE -ne 0) {
  throw 'Could not verify the enabled serverless APIs.'
}

$missingApis = @($apis | Where-Object { $enabledApis -notcontains $_ })
$unexpectedApis = @($enabledApis | Where-Object { $apis -notcontains $_ })
if ($missingApis.Count -gt 0 -or $unexpectedApis.Count -gt 0) {
  throw "Enabled API verification mismatch. Missing: $($missingApis -join ', '); unexpected: $($unexpectedApis -join ', ')"
}

$enabledApis | Sort-Object
