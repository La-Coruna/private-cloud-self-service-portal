$ErrorActionPreference = 'Stop'

$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..\02-create-firestore.ps1')).Path
$tokens = $null
$parseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors) | Out-Null
if ($parseErrors.Count -ne 0) {
  throw "PowerShell syntax check failed: $($parseErrors.Message -join '; ')"
}

. $scriptPath

function Assert-Equal {
  param($Expected, $Actual, [string]$Because)
  if ($Expected -cne $Actual) {
    throw "Expected '$Expected' but got '$Actual': $Because"
  }
}

$script:fake = [ordered]@{
  Created = $false
  ExistingJson = $null
  CreateCalls = 0
  Commands = [System.Collections.Generic.List[string]]::new()
}

function gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)

  $command = ($CommandArgs | ForEach-Object { [string]$_ }) -join ' '
  $script:fake.Commands.Add($command)
  $global:LASTEXITCODE = 0

  if ($command -eq 'config get-value project') {
    return 'private-cloud-portal-demo-2'
  }
  if ($command -eq 'auth list --filter=status:ACTIVE --format=value(account)') {
    return 'approved@example.invalid'
  }
  if ($command -eq 'projects describe private-cloud-portal-demo-2 --format=value(projectId)') {
    return 'private-cloud-portal-demo-2'
  }
  if ($command -eq 'firestore databases describe --database=(default) --project=private-cloud-portal-demo-2 --format=json') {
    if ($null -ne $script:fake.ExistingJson) {
      return $script:fake.ExistingJson
    }
    if ($script:fake.Created) {
      return '{"name":"projects/private-cloud-portal-demo-2/databases/(default)","locationId":"asia-northeast3","type":"FIRESTORE_NATIVE"}'
    }
    $global:LASTEXITCODE = 1
    Write-Error 'NOT_FOUND: the default database does not exist.'
    return
  }
  if ($command -eq 'firestore databases list --project=private-cloud-portal-demo-2 --format=json') {
    return '[]'
  }
  if ($command -eq 'firestore databases create --database=(default) --location=asia-northeast3 --type=firestore-native --project=private-cloud-portal-demo-2') {
    $script:fake.CreateCalls++
    $script:fake.Created = $true
    return
  }

  throw "Unexpected gcloud command in contract test: $command"
}

$firstRun = @(Invoke-FirestoreDatabaseProvisioning `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredAccount 'approved@example.invalid')
Assert-Equal 'created' (($firstRun[0] -split '=', 2)[1]) 'the absent database should be created'
Assert-Equal 1 $script:fake.CreateCalls 'the first run should issue exactly one create command'
Assert-Equal 'asia-northeast3' (($firstRun[1] -split '=', 2)[1]) 'post-create verification should report Seoul'
Assert-Equal 'FIRESTORE_NATIVE' (($firstRun[2] -split '=', 2)[1]) 'post-create verification should report Native mode'

$secondRun = @(Invoke-FirestoreDatabaseProvisioning `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredAccount 'approved@example.invalid')
Assert-Equal 'no-op' (($secondRun[0] -split '=', 2)[1]) 'a repeat run should be idempotent'
Assert-Equal 1 $script:fake.CreateCalls 'the repeat run must not issue another create command'

$script:fake.ExistingJson = '{"name":"projects/private-cloud-portal-demo-2/databases/(default)","locationId":"nam5","type":"FIRESTORE_NATIVE"}'
try {
  Invoke-FirestoreDatabaseProvisioning `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredAccount 'approved@example.invalid' | Out-Null
  throw 'Expected the wrong-location database to stop provisioning.'
}
catch {
  if ($_.Exception.Message -eq 'Expected the wrong-location database to stop provisioning.') {
    throw
  }
}
Assert-Equal 1 $script:fake.CreateCalls 'an incompatible existing database must never trigger creation'

Write-Output 'Firestore script syntax and command contract tests passed.'
