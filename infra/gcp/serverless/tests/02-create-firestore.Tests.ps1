$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot '..\02-create-firestore.ps1'
. $scriptPath

function Assert-Equal {
  param(
    [Parameter(Mandatory = $true)]$Expected,
    [Parameter(Mandatory = $true)]$Actual,
    [Parameter(Mandatory = $true)][string]$Because
  )

  if ($Expected -cne $Actual) {
    throw "Expected '$Expected' but got '$Actual': $Because"
  }
}

function Assert-Throws {
  param(
    [Parameter(Mandatory = $true)][scriptblock]$Action,
    [Parameter(Mandatory = $true)][string]$Because
  )

  try {
    & $Action
  }
  catch {
    return
  }

  throw "Expected an exception: $Because"
}

$seoulNative = '{"name":"projects/example/databases/(default)","locationId":"asia-northeast3","type":"FIRESTORE_NATIVE"}'
$wrongLocation = '{"name":"projects/example/databases/(default)","locationId":"nam5","type":"FIRESTORE_NATIVE"}'
$wrongType = '{"name":"projects/example/databases/(default)","locationId":"asia-northeast3","type":"DATASTORE_MODE"}'

Assert-Equal -Expected 'Create' -Actual (Get-FirestoreDatabaseDecision -DatabaseJson $null) `
  -Because 'an absent default database must be created'
Assert-Equal -Expected 'NoOp' -Actual (Get-FirestoreDatabaseDecision -DatabaseJson $seoulNative) `
  -Because 'an existing Seoul Native database must be preserved'
Assert-Throws -Action { Get-FirestoreDatabaseDecision -DatabaseJson $wrongLocation } `
  -Because 'Firestore location is immutable and a non-Seoul database must stop the script'
Assert-Throws -Action { Get-FirestoreDatabaseDecision -DatabaseJson $wrongType } `
  -Because 'Datastore mode must never be accepted as Firestore Native'

Write-Output 'Firestore decision fixtures passed: absent, Seoul Native, wrong location, wrong type.'
