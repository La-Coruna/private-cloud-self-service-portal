[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2',
  [string]$ClusterName = 'portal-demo-standard',
  [string]$Zone = 'asia-northeast3-a',
  [string]$ExpectedAccount = 'yougood260807@gmail.com'
)

$ErrorActionPreference = 'Stop'
$script:approvedProjectId = 'private-cloud-portal-demo-2'
$script:approvedClusterName = 'portal-demo-standard'
$script:approvedZone = 'asia-northeast3-a'
$script:approvedAccount = 'yougood260807@gmail.com'

function Assert-ExactPropertySet {
  param(
    [Parameter(Mandatory = $true)]$Object,
    [Parameter(Mandatory = $true)][string[]]$ExpectedNames,
    [Parameter(Mandatory = $true)][string]$Description
  )

  $actualNames = @($Object.PSObject.Properties.Name | Sort-Object)
  $expected = @($ExpectedNames | Sort-Object)
  if (($actualNames -join ',') -cne ($expected -join ',')) {
    throw "$Description contains missing or unexpected fields. Expected: $($expected -join ', '); found: $($actualNames -join ', ')"
  }
}

function Assert-ApprovedIdentifiers {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  if ($RequiredProjectId -cne $script:approvedProjectId) {
    throw 'The requested project is not the approved serverless migration project.'
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

function Assert-GcloudContext {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
    throw 'gcloud CLI is unavailable.'
  }

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

function Get-GkeClusterDescription {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone
  )

  $json = & gcloud container clusters describe $RequiredClusterName `
    --zone $RequiredZone --project $RequiredProjectId --format=json 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw 'Could not describe the approved GKE cluster.'
  }

  try {
    return (($json -join "`n") | ConvertFrom-Json)
  }
  catch {
    throw 'GKE cluster describe returned malformed JSON.'
  }
}

function Get-ValidatedEndpointSnapshot {
  param(
    [Parameter(Mandatory = $true)]$Cluster,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone
  )

  if ($Cluster.name -cne $RequiredClusterName -or $Cluster.location -cne $RequiredZone) {
    throw 'GKE cluster metadata does not match the approved cluster and zone.'
  }
  if ($Cluster.status -cne 'RUNNING') {
    throw "The approved GKE cluster is not RUNNING: $($Cluster.status)"
  }
  if ($null -eq $Cluster.controlPlaneEndpointsConfig) {
    throw 'GKE control-plane endpoint configuration is absent.'
  }

  Assert-ExactPropertySet -Object $Cluster.controlPlaneEndpointsConfig `
    -ExpectedNames @('dnsEndpointConfig', 'ipEndpointsConfig') `
    -Description 'Control-plane endpoint configuration'

  $dns = $Cluster.controlPlaneEndpointsConfig.dnsEndpointConfig
  $ip = $Cluster.controlPlaneEndpointsConfig.ipEndpointsConfig
  if ($null -eq $dns -or $null -eq $ip) {
    throw 'GKE DNS or IP endpoint configuration is absent.'
  }

  Assert-ExactPropertySet -Object $dns `
    -ExpectedNames @('allowExternalTraffic', 'enableK8sCertsViaDns', 'enableK8sTokensViaDns', 'endpoint') `
    -Description 'DNS endpoint configuration'
  Assert-ExactPropertySet -Object $ip `
    -ExpectedNames @('authorizedNetworksConfig', 'enablePublicEndpoint', 'enabled', 'privateEndpoint', 'publicEndpoint') `
    -Description 'IP endpoint configuration'

  foreach ($propertyName in @('allowExternalTraffic', 'enableK8sCertsViaDns', 'enableK8sTokensViaDns')) {
    if ($dns.$propertyName -isnot [bool]) {
      throw "DNS endpoint flag '$propertyName' is missing or is not Boolean."
    }
  }
  foreach ($propertyName in @('enablePublicEndpoint', 'enabled')) {
    if ($ip.$propertyName -isnot [bool]) {
      throw "IP endpoint flag '$propertyName' is missing or is not Boolean."
    }
  }

  if ([string]::IsNullOrWhiteSpace([string]$dns.endpoint)) {
    throw 'The GKE DNS endpoint is absent.'
  }
  if ($dns.enableK8sTokensViaDns -or $dns.enableK8sCertsViaDns) {
    throw 'Kubernetes tokens and certificates via DNS must remain disabled.'
  }
  if (-not $ip.enabled -or -not $ip.enablePublicEndpoint) {
    throw 'The existing public IP endpoint must remain enabled for rollback.'
  }
  if ([string]::IsNullOrWhiteSpace([string]$ip.publicEndpoint)) {
    throw 'The existing public IP endpoint is absent.'
  }
  if ([string]::IsNullOrWhiteSpace([string]$ip.privateEndpoint)) {
    throw 'The existing private IP endpoint is absent.'
  }
  if ($null -eq $ip.authorizedNetworksConfig) {
    throw 'Authorized-networks configuration is absent.'
  }
  $authorizedNetworkProperties = @($ip.authorizedNetworksConfig.PSObject.Properties)
  if ($authorizedNetworkProperties.Count -ne 0) {
    throw 'Authorized-networks configuration changed from the approved empty baseline.'
  }

  return [ordered]@{
    dnsAllowExternalTraffic = $dns.allowExternalTraffic
    dnsEnableK8sTokensViaDns = $dns.enableK8sTokensViaDns
    dnsEnableK8sCertsViaDns = $dns.enableK8sCertsViaDns
    dnsEndpointPresent = $true
    ipEndpointsEnabled = $ip.enabled
    publicIpEndpointEnabled = $ip.enablePublicEndpoint
    publicIpEndpointPresent = $true
    privateIpEndpointPresent = $true
    authorizedNetworksConfigured = $false
  }
}

function Write-SanitizedEndpointSnapshot {
  param(
    [Parameter(Mandatory = $true)][string]$Prefix,
    [Parameter(Mandatory = $true)]$Snapshot
  )

  foreach ($name in @(
    'dnsAllowExternalTraffic',
    'dnsEnableK8sTokensViaDns',
    'dnsEnableK8sCertsViaDns',
    'dnsEndpointPresent',
    'ipEndpointsEnabled',
    'publicIpEndpointEnabled',
    'publicIpEndpointPresent',
    'privateIpEndpointPresent',
    'authorizedNetworksConfigured'
  )) {
    Write-Output "$Prefix.$name=$($Snapshot[$name])"
  }
}

function Invoke-GkeDnsEndpointEnablement {
  param(
    [Parameter(Mandatory = $true)][string]$RequiredProjectId,
    [Parameter(Mandatory = $true)][string]$RequiredClusterName,
    [Parameter(Mandatory = $true)][string]$RequiredZone,
    [Parameter(Mandatory = $true)][string]$RequiredAccount
  )

  Assert-ApprovedIdentifiers -RequiredProjectId $RequiredProjectId `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone `
    -RequiredAccount $RequiredAccount
  Assert-GcloudContext -RequiredProjectId $RequiredProjectId -RequiredAccount $RequiredAccount

  $beforeCluster = Get-GkeClusterDescription -RequiredProjectId $RequiredProjectId `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone
  $before = Get-ValidatedEndpointSnapshot -Cluster $beforeCluster `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone

  if ($before.dnsAllowExternalTraffic) {
    $result = 'no-op'
  }
  else {
    & gcloud container clusters update $RequiredClusterName `
      --zone $RequiredZone `
      --project $RequiredProjectId `
      --enable-dns-access | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw 'Could not enable external access to the GKE DNS endpoint.'
    }
    $result = 'enabled'
  }

  $afterCluster = Get-GkeClusterDescription -RequiredProjectId $RequiredProjectId `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone
  $after = Get-ValidatedEndpointSnapshot -Cluster $afterCluster `
    -RequiredClusterName $RequiredClusterName -RequiredZone $RequiredZone
  if (-not $after.dnsAllowExternalTraffic) {
    throw 'GKE DNS endpoint verification did not reach the approved external-access state.'
  }

  Write-Output "result=$result"
  Write-SanitizedEndpointSnapshot -Prefix 'before' -Snapshot $before
  Write-SanitizedEndpointSnapshot -Prefix 'after' -Snapshot $after
}

if ($MyInvocation.InvocationName -ne '.') {
  Invoke-GkeDnsEndpointEnablement -RequiredProjectId $ProjectId `
    -RequiredClusterName $ClusterName -RequiredZone $Zone -RequiredAccount $ExpectedAccount
}
