$ErrorActionPreference = 'Stop'

$scriptPath = (Resolve-Path (Join-Path $PSScriptRoot '..\04-enable-gke-dns-endpoint.ps1')).Path
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

function Assert-ThrowsBeforeUpdate {
  param([scriptblock]$Action, [string]$Because)

  $before = $script:fake.UpdateCalls
  try {
    & $Action
  }
  catch {
    Assert-Equal $before $script:fake.UpdateCalls "$Because; no update may run"
    return
  }

  throw "Expected an exception: $Because"
}

function New-ClusterJson {
  param(
    [bool]$AllowExternalTraffic = $false,
    [bool]$EnableK8sTokensViaDns = $false,
    [bool]$EnableK8sCertsViaDns = $false,
    [bool]$IpEnabled = $true,
    [bool]$EnablePublicEndpoint = $true,
    [string]$Name = 'portal-demo-standard',
    [string]$Location = 'asia-northeast3-a'
  )

  return ([ordered]@{
    name = $Name
    location = $Location
    status = 'RUNNING'
    controlPlaneEndpointsConfig = [ordered]@{
      dnsEndpointConfig = [ordered]@{
        allowExternalTraffic = $AllowExternalTraffic
        enableK8sCertsViaDns = $EnableK8sCertsViaDns
        enableK8sTokensViaDns = $EnableK8sTokensViaDns
        endpoint = 'cluster.example.invalid'
      }
      ipEndpointsConfig = [ordered]@{
        authorizedNetworksConfig = [ordered]@{}
        enablePublicEndpoint = $EnablePublicEndpoint
        enabled = $IpEnabled
        privateEndpoint = '10.0.0.1'
        publicEndpoint = '192.0.2.1'
      }
    }
  } | ConvertTo-Json -Depth 8 -Compress)
}

$script:fake = [ordered]@{
  ActiveAccount = 'yougood260807@gmail.com'
  ActiveProject = 'private-cloud-portal-demo-2'
  ClusterJson = New-ClusterJson
  UpdateCalls = 0
  Commands = [System.Collections.Generic.List[string]]::new()
}

function gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)

  $command = ($CommandArgs | ForEach-Object { [string]$_ }) -join ' '
  $script:fake.Commands.Add($command)
  $global:LASTEXITCODE = 0

  if ($command -eq 'config get-value project') { return $script:fake.ActiveProject }
  if ($command -eq 'auth list --filter=status:ACTIVE --format=value(account)') { return $script:fake.ActiveAccount }
  if ($command -eq 'projects describe private-cloud-portal-demo-2 --format=value(projectId)') {
    return 'private-cloud-portal-demo-2'
  }
  if ($command -eq 'container clusters describe portal-demo-standard --zone asia-northeast3-a --project private-cloud-portal-demo-2 --format=json') {
    return $script:fake.ClusterJson
  }
  if ($command -eq 'container clusters update portal-demo-standard --zone asia-northeast3-a --project private-cloud-portal-demo-2 --enable-dns-access') {
    $script:fake.UpdateCalls++
    $script:fake.ClusterJson = New-ClusterJson -AllowExternalTraffic $true
    return
  }

  throw "Unexpected gcloud command in contract test: $command"
}

$first = @(Invoke-GkeDnsEndpointEnablement `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredClusterName 'portal-demo-standard' `
  -RequiredZone 'asia-northeast3-a' `
  -RequiredAccount 'yougood260807@gmail.com')
Assert-Equal 1 $script:fake.UpdateCalls 'the disabled DNS endpoint should be enabled exactly once'
Assert-Equal 'result=enabled' $first[0] 'the first run should report enablement'
Assert-Equal 'before.dnsAllowExternalTraffic=False' $first[1] 'the before snapshot must be sanitized and complete'
Assert-Equal 'after.dnsAllowExternalTraffic=True' $first[10] 'the after snapshot must prove external DNS traffic is enabled'

$second = @(Invoke-GkeDnsEndpointEnablement `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredClusterName 'portal-demo-standard' `
  -RequiredZone 'asia-northeast3-a' `
  -RequiredAccount 'yougood260807@gmail.com')
Assert-Equal 1 $script:fake.UpdateCalls 'the repeat run must not issue a second update'
Assert-Equal 'result=no-op' $second[0] 'the repeat run should report no-op'

$script:fake.ActiveAccount = 'itsokay260617@gmail.com'
Assert-ThrowsBeforeUpdate -Because 'the previous deployment account must be rejected' -Action {
  Invoke-GkeDnsEndpointEnablement `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}
$script:fake.ActiveAccount = 'yougood260807@gmail.com'

$script:fake.ClusterJson = New-ClusterJson -EnableK8sTokensViaDns $true
Assert-ThrowsBeforeUpdate -Because 'Kubernetes tokens via DNS must remain disabled' -Action {
  Invoke-GkeDnsEndpointEnablement `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}

$script:fake.ClusterJson = New-ClusterJson -EnablePublicEndpoint $false
Assert-ThrowsBeforeUpdate -Because 'the public IP endpoint must be retained for rollback' -Action {
  Invoke-GkeDnsEndpointEnablement `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}

$script:fake.ClusterJson = New-ClusterJson -Location 'asia-northeast3-b'
Assert-ThrowsBeforeUpdate -Because 'unexpected cluster location must stop execution' -Action {
  Invoke-GkeDnsEndpointEnablement `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}

Write-Output 'GKE DNS endpoint script syntax and command contract tests passed.'
