[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2',
  [string]$ExpectedAccount = 'yougood260807@gmail.com'
)

$ErrorActionPreference = 'Stop'

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

function Test-ServiceAccountExists {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$Email
  )

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $describeOutput = & gcloud iam service-accounts describe $Email `
      --project=$RequiredProjectId --format='value(email)' 2>$null
    $describedEmail = ($describeOutput -join "`n").Trim()
    $describeExitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }

  if ($describeExitCode -eq 0) {
    if ($describedEmail -cne $Email) {
      throw 'Service account describe returned an unexpected identity.'
    }
    return $true
  }

  $listOutput = & gcloud iam service-accounts list --project=$RequiredProjectId `
    --filter="email:$Email" --format='value(email)' 2>$null
  $listedEmail = ($listOutput -join "`n").Trim()
  if ($LASTEXITCODE -ne 0) {
    throw 'Could not distinguish an absent service account from a describe failure.'
  }
  if (-not [string]::IsNullOrWhiteSpace($listedEmail)) {
    throw 'The target service account exists but could not be described safely.'
  }

  return $false
}

function Get-DirectProjectRoleBindings {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$Member
  )

  $policyOutput = & gcloud projects get-iam-policy $RequiredProjectId --format=json 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw 'Could not read the project IAM policy.'
  }

  try {
    $policy = (($policyOutput -join "`n") | ConvertFrom-Json)
  }
  catch {
    throw 'Project IAM policy returned malformed JSON.'
  }

  return @(
    $policy.bindings | Where-Object { @($_.members) -ccontains $Member }
  )
}

function Assert-ApprovedRoleBindings {
  param(
    [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Bindings,
    [Parameter(Mandatory = $true)][string[]]$AllowedRoles
  )

  $unexpectedRoles = @(
    $Bindings | Where-Object { $AllowedRoles -notcontains $_.role } | ForEach-Object { $_.role }
  )
  if ($unexpectedRoles.Count -gt 0) {
    throw "The runtime identity has unexpected project roles: $($unexpectedRoles -join ', '). Refusing to modify them automatically."
  }

  $conditionalRoles = @(
    $Bindings | Where-Object { $null -ne $_.condition } | ForEach-Object { $_.role }
  )
  if ($conditionalRoles.Count -gt 0) {
    throw "The runtime identity has conditional project bindings: $($conditionalRoles -join ', '). Refusing an ambiguous IAM configuration."
  }
}

function Invoke-CloudRunIdentityConfiguration {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [string]$RequiredAccount
  )

  Assert-GcloudContext -RequiredProjectId $RequiredProjectId -RequiredAccount $RequiredAccount

  $email = "portal-cloud-run@$RequiredProjectId.iam.gserviceaccount.com"
  $member = "serviceAccount:$email"
  $roles = @('roles/datastore.user', 'roles/container.viewer', 'roles/logging.logWriter')
  $exists = Test-ServiceAccountExists -RequiredProjectId $RequiredProjectId -Email $email

  if ($exists) {
    $existingBindings = @(Get-DirectProjectRoleBindings -RequiredProjectId $RequiredProjectId -Member $member)
    Assert-ApprovedRoleBindings -Bindings $existingBindings -AllowedRoles $roles
    $result = 'no-op'
  }
  else {
    & gcloud iam service-accounts create portal-cloud-run --project=$RequiredProjectId `
      --display-name='Portal Cloud Run runtime'
    if ($LASTEXITCODE -ne 0) {
      throw 'The Cloud Run runtime service account could not be created.'
    }
    $result = 'created'
    $existingBindings = @()
  }

  $existingRoles = @($existingBindings | ForEach-Object { $_.role })
  foreach ($role in $roles) {
    if ($existingRoles -notcontains $role) {
      & gcloud projects add-iam-policy-binding $RequiredProjectId --member=$member `
        --role=$role --condition=None --quiet | Out-Null
      if ($LASTEXITCODE -ne 0) {
        throw "Could not grant the approved role: $role"
      }
      if ($result -eq 'no-op') { $result = 'configured' }
    }
  }

  $verifiedBindings = @(Get-DirectProjectRoleBindings -RequiredProjectId $RequiredProjectId -Member $member)
  Assert-ApprovedRoleBindings -Bindings $verifiedBindings -AllowedRoles $roles
  $verifiedRoles = @($verifiedBindings | ForEach-Object { $_.role } | Sort-Object -Unique)
  $expectedRoles = @($roles | Sort-Object -Unique)
  if (($verifiedRoles -join ',') -cne ($expectedRoles -join ',')) {
    throw "IAM verification mismatch. Expected exactly: $($expectedRoles -join ', '); found: $($verifiedRoles -join ', ')"
  }

  Write-Output "result=$result"
  Write-Output "serviceAccount=$email"
  $verifiedRoles | ForEach-Object { Write-Output "role=$_" }
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-CloudRunIdentityConfiguration -RequiredProjectId $ProjectId -RequiredAccount $ExpectedAccount
}
