[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2',
  [string]$ExpectedAccount = 'yougood260807@gmail.com'
)

$ErrorActionPreference = 'Stop'
$expectedLocation = 'asia-northeast3'
$expectedType = 'FIRESTORE_NATIVE'

function Get-FirestoreDatabaseDecision {
  param(
    [AllowNull()]
    [AllowEmptyString()]
    [string]$DatabaseJson
  )

  if ([string]::IsNullOrWhiteSpace($DatabaseJson)) {
    return 'Create'
  }

  try {
    $database = $DatabaseJson | ConvertFrom-Json
  }
  catch {
    throw 'Firestore describe returned malformed JSON.'
  }

  if ($database.locationId -cne $script:expectedLocation) {
    throw "The existing default database is in '$($database.locationId)', not '$script:expectedLocation'. Firestore location is immutable."
  }

  if ($database.type -cne $script:expectedType) {
    throw "The existing default database type is '$($database.type)', not '$script:expectedType'."
  }

  return 'NoOp'
}

function Assert-GcloudContext {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [string]$RequiredAccount
  )

  if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw 'gcloud CLI is unavailable.'
  }

  $activeProject = (& gcloud config get-value project 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $activeProject -cne $RequiredProjectId) {
    throw 'The active gcloud project does not match the requested project.'
  }

  if (-not [string]::IsNullOrWhiteSpace($RequiredAccount)) {
    $activeAccount = (& gcloud auth list --filter='status:ACTIVE' --format='value(account)' 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or $activeAccount -cne $RequiredAccount) {
      throw 'The active gcloud account does not match the approved deployment account.'
    }
  }

  $resolvedProject = (& gcloud projects describe $RequiredProjectId --format='value(projectId)' 2>$null).Trim()
  if ($LASTEXITCODE -ne 0 -or $resolvedProject -cne $RequiredProjectId) {
    throw 'The requested GCP project is not accessible.'
  }
}

function Get-DefaultFirestoreDatabaseJson {
  param([Parameter(Mandatory = $true)][string]$RequiredProjectId)

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $existing = & gcloud firestore databases describe --database='(default)' --project=$RequiredProjectId --format=json 2>$null
    $describeExitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }

  if ($describeExitCode -eq 0) {
    $databaseJson = ($existing -join "`n").Trim()
    if ([string]::IsNullOrWhiteSpace($databaseJson)) {
      throw 'Firestore describe succeeded without returning database metadata.'
    }
    return $databaseJson
  }

  $databaseListOutput = & gcloud firestore databases list --project=$RequiredProjectId --format=json 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw 'Could not distinguish an absent default Firestore database from a describe failure.'
  }

  $databaseListJson = ($databaseListOutput -join "`n").Trim()
  try {
    $databases = @($databaseListJson | ConvertFrom-Json)
  }
  catch {
    throw 'Firestore database list returned malformed JSON.'
  }

  $defaultDatabase = @(
    $databases | Where-Object {
      $_.name -eq '(default)' -or $_.name -like '*/databases/(default)'
    }
  )
  if ($defaultDatabase.Count -gt 0) {
    throw 'The default Firestore database exists but could not be described safely.'
  }

  return $null
}

function Invoke-FirestoreDatabaseProvisioning {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [string]$RequiredAccount
  )

  Assert-GcloudContext -RequiredProjectId $RequiredProjectId -RequiredAccount $RequiredAccount
  $databaseJson = Get-DefaultFirestoreDatabaseJson -RequiredProjectId $RequiredProjectId
  $decision = Get-FirestoreDatabaseDecision -DatabaseJson $databaseJson

  if ($decision -eq 'Create') {
    & gcloud firestore databases create --database='(default)' --location=$script:expectedLocation `
      --type=firestore-native --project=$RequiredProjectId
    if ($LASTEXITCODE -ne 0) {
      throw 'The default Firestore Native database could not be created.'
    }
    $result = 'created'
  }
  else {
    $result = 'no-op'
  }

  $verifiedJson = Get-DefaultFirestoreDatabaseJson -RequiredProjectId $RequiredProjectId
  $verifiedDecision = Get-FirestoreDatabaseDecision -DatabaseJson $verifiedJson
  if ($verifiedDecision -ne 'NoOp') {
    throw 'Firestore post-provision verification did not reach the expected state.'
  }

  $verified = $verifiedJson | ConvertFrom-Json
  Write-Output "result=$result"
  Write-Output "locationId=$($verified.locationId)"
  Write-Output "type=$($verified.type)"
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-FirestoreDatabaseProvisioning -RequiredProjectId $ProjectId -RequiredAccount $ExpectedAccount
}
