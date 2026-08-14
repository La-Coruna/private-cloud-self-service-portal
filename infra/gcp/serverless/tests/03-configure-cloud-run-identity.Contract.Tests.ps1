$ErrorActionPreference = 'Stop'

$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..\03-configure-cloud-run-identity.ps1')).Path
$manifestPath = (Resolve-Path (Join-Path $PSScriptRoot '..\cloud-run-gke-rbac.yaml')).Path

$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -ne 0) {
  throw "PowerShell syntax check failed: $($parseErrors.Message -join '; ')"
}

function Assert-Equal {
  param($Expected, $Actual, [string]$Because)
  if ($Expected -cne $Actual) {
    throw "Expected '$Expected' but got '$Actual': $Because"
  }
}

function Assert-SetEqual {
  param([string[]]$Expected, [string[]]$Actual, [string]$Because)
  $expectedSorted = @($Expected | Sort-Object -Unique)
  $actualSorted = @($Actual | Sort-Object -Unique)
  Assert-Equal ($expectedSorted -join ',') ($actualSorted -join ',') $Because
}

. $scriptPath

$script:fake = [ordered]@{
  AccountExists = $false
  AccountCreates = 0
  Roles = [System.Collections.Generic.List[string]]::new()
}

function gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)
  $command = ($CommandArgs | ForEach-Object { [string]$_ }) -join ' '
  $global:LASTEXITCODE = 0

  if ($command -eq 'config get-value project') { return 'private-cloud-portal-demo-2' }
  if ($command -eq 'auth list --filter=status:ACTIVE --format=value(account)') { return 'approved@example.invalid' }
  if ($command -eq 'projects describe private-cloud-portal-demo-2 --format=value(projectId)') { return 'private-cloud-portal-demo-2' }
  if ($command -eq 'iam service-accounts describe portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com --project=private-cloud-portal-demo-2 --format=value(email)') {
    if ($script:fake.AccountExists) { return 'portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com' }
    $global:LASTEXITCODE = 1
    return
  }
  if ($command -eq 'iam service-accounts list --project=private-cloud-portal-demo-2 --filter=email:portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com --format=value(email)') {
    if ($script:fake.AccountExists) { return 'portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com' }
    return
  }
  if ($command -eq 'iam service-accounts create portal-cloud-run --project=private-cloud-portal-demo-2 --display-name=Portal Cloud Run runtime') {
    $script:fake.AccountCreates++
    $script:fake.AccountExists = $true
    return
  }
  if ($command -eq 'projects get-iam-policy private-cloud-portal-demo-2 --format=json') {
    $bindings = @($script:fake.Roles | ForEach-Object {
      [ordered]@{ role = $_; members = @('serviceAccount:portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com') }
    })
    return ([ordered]@{ bindings = $bindings } | ConvertTo-Json -Depth 5 -Compress)
  }
  if ($command -match '^projects add-iam-policy-binding private-cloud-portal-demo-2 --member=serviceAccount:portal-cloud-run@private-cloud-portal-demo-2\.iam\.gserviceaccount\.com --role=(roles/[A-Za-z.]+) --condition=None --quiet$') {
    if (-not $script:fake.Roles.Contains($Matches[1])) { $script:fake.Roles.Add($Matches[1]) }
    return
  }

  throw "Unexpected gcloud command in contract test: $command"
}

$expectedRoles = @('roles/datastore.user', 'roles/container.viewer', 'roles/logging.logWriter')
$first = @(Invoke-CloudRunIdentityConfiguration -RequiredProjectId 'private-cloud-portal-demo-2' -RequiredAccount 'approved@example.invalid')
Assert-Equal 1 $script:fake.AccountCreates 'an absent runtime identity should be created exactly once'
Assert-SetEqual $expectedRoles @($script:fake.Roles) 'only the three approved roles may be granted'
Assert-Equal 'result=created' $first[0] 'the first run should report account creation'

$second = @(Invoke-CloudRunIdentityConfiguration -RequiredProjectId 'private-cloud-portal-demo-2' -RequiredAccount 'approved@example.invalid')
Assert-Equal 1 $script:fake.AccountCreates 'a repeat run must not recreate the identity'
Assert-SetEqual $expectedRoles @($script:fake.Roles) 'a repeat run must preserve the exact approved role set'
Assert-Equal 'result=no-op' $second[0] 'the repeat run should report no-op'

$script:fake.Roles.Add('roles/editor')
try {
  Invoke-CloudRunIdentityConfiguration -RequiredProjectId 'private-cloud-portal-demo-2' -RequiredAccount 'approved@example.invalid' | Out-Null
  throw 'Expected an unexpected role to stop configuration.'
}
catch {
  if ($_.Exception.Message -eq 'Expected an unexpected role to stop configuration.') { throw }
}
Assert-SetEqual (@($expectedRoles) + 'roles/editor') @($script:fake.Roles) 'an unexpected role must never be removed or concealed automatically'

$manifest = Get-Content -Raw -LiteralPath $manifestPath
if ($manifest -notmatch 'kind:\s+User\s+[\s\S]*?name:\s+portal-cloud-run@private-cloud-portal-demo-2\.iam\.gserviceaccount\.com') {
  throw 'RBAC subject must be the exact IAM service account as a User.'
}

$allowedResources = @('deployments', 'events', 'ingresses', 'namespaces', 'pods', 'resourcequotas', 'services')
$resourceMatches = [regex]::Matches($manifest, '(?m)^\s+-\s+(namespaces|resourcequotas|services|pods|events|deployments|ingresses)\s*$')
Assert-SetEqual $allowedResources @($resourceMatches | ForEach-Object { $_.Groups[1].Value }) 'RBAC resources must be the exact approved set'

$verbMatches = [regex]::Matches($manifest, '(?m)^\s+-\s+(get|list|watch|create|delete)\s*$')
Assert-SetEqual @('get', 'list', 'watch', 'create', 'delete') @($verbMatches | ForEach-Object { $_.Groups[1].Value }) 'RBAC verbs must be the exact approved set'

if ($manifest -match '(?im)^\s+-\s+(secrets|nodes|pods/exec|pods/log|roles|rolebindings|clusterroles|clusterrolebindings)\s*$') {
  throw 'RBAC manifest includes a forbidden resource.'
}

function Assert-KubectlPermission {
  param(
    [Parameter(Mandatory = $true)][string]$Verb,
    [Parameter(Mandatory = $true)][string]$Resource,
    [string]$Subresource,
    [Parameter(Mandatory = $true)][ValidateSet('yes', 'no')][string]$Expected
  )

  $identity = 'portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com'
  $arguments = @('auth', 'can-i', $Verb, $Resource)
  if (-not [string]::IsNullOrWhiteSpace($Subresource)) {
    $arguments += "--subresource=$Subresource"
  }
  $arguments += "--as=$identity"
  $arguments += '--all-namespaces'

  $answer = (& kubectl @arguments 2>$null | Out-String).Trim()
  if ($LASTEXITCODE -notin @(0, 1)) {
    throw "kubectl auth check failed for $Verb $Resource subresource '$Subresource'."
  }
  Assert-Equal $Expected $answer "unexpected live Kubernetes authorization result for $Verb $Resource subresource '$Subresource'"
}

Assert-KubectlPermission -Verb create -Resource deployments -Expected yes
Assert-KubectlPermission -Verb delete -Resource namespaces -Expected yes
Assert-KubectlPermission -Verb get -Resource secrets -Expected no
Assert-KubectlPermission -Verb create -Resource clusterroles -Expected no
Assert-KubectlPermission -Verb update -Resource nodes -Expected no
Assert-KubectlPermission -Verb create -Resource pods -Subresource exec -Expected no
Assert-KubectlPermission -Verb get -Resource pods -Subresource log -Expected no

Write-Output 'Cloud Run identity script and least-privilege RBAC contract tests passed.'
