[CmdletBinding()]
param(
  [string]$BaseUri = 'https://private-cloud-portal-demo-2.web.app',
  [ValidateRange(30, 900)][int]$TimeoutSeconds = 300,
  [ValidateRange(1, 30)][int]$PollSeconds = 5
)

$ErrorActionPreference = 'Stop'

function Invoke-PortalRequest {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [ValidateSet('GET', 'POST', 'DELETE')][string]$Method = 'GET',
    [object]$Body
  )

  $uri = '{0}/{1}' -f $BaseUri.TrimEnd('/'), $Path.TrimStart('/')
  $parameters = @{
    Uri = $uri
    Method = $Method
    Headers = @{ Accept = 'application/json' }
    TimeoutSec = 30
  }
  if ($null -ne $Body) {
    $parameters.ContentType = 'application/json'
    $parameters.Body = $Body | ConvertTo-Json -Depth 8 -Compress
  }
  Invoke-RestMethod @parameters
}

function ConvertTo-PortalArray {
  param([object]$Value)

  $items = [System.Collections.Generic.List[object]]::new()
  if ($null -eq $Value) {
    return $items.ToArray()
  }
  foreach ($item in @($Value)) {
    if ($item -is [System.Array]) {
      foreach ($nestedItem in $item) {
        $items.Add($nestedItem)
      }
    }
    else {
      $items.Add($item)
    }
  }
  return $items.ToArray()
}

function Wait-ProjectStatus {
  param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string[]]$ExpectedStatus
  )

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $project = Invoke-PortalRequest -Path "/api/projects/$ProjectId"
    if ($ExpectedStatus -ccontains [string]$project.status) {
      return $project
    }
    if ($project.status -ceq 'FAILED') {
      throw "Smoke project failed: $($project.error_message)"
    }
    Start-Sleep -Seconds $PollSeconds
  } while ((Get-Date) -lt $deadline)

  throw "Timed out waiting for project=$ProjectId status=$($ExpectedStatus -join ',')."
}

function Wait-ProjectSyncStatus {
  param([Parameter(Mandatory = $true)][string]$ProjectId)

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  do {
    $project = Invoke-PortalRequest `
      -Path "/api/projects/$ProjectId/sync-status" -Method 'POST'
    if ($project.status -ceq 'RUNNING') {
      return $project
    }
    if ($project.status -ceq 'FAILED') {
      throw "Smoke project sync failed: $($project.error_message)"
    }
    Start-Sleep -Seconds $PollSeconds
  } while ((Get-Date) -lt $deadline)

  throw "Timed out waiting for project=$ProjectId sync status RUNNING."
}

function Assert-CleanCapacity {
  $response = Invoke-PortalRequest -Path '/api/projects'
  $projects = @(ConvertTo-PortalArray -Value $response)
  $active = @($projects | Where-Object { $_.status -cne 'DELETED' })
  if ($active.Count -ne 0) {
    $summary = ($active | ForEach-Object { "$($_.id):$($_.status)" }) -join ', '
    throw "Smoke test requires no active project. Found: $summary"
  }
}

function Assert-AuditSequence {
  param(
    [Parameter(Mandatory = $true)][object[]]$Audits,
    [Parameter(Mandatory = $true)][string[]]$RequiredActions
  )

  $cursor = -1
  foreach ($action in $RequiredActions) {
    $match = $null
    for ($index = $cursor + 1; $index -lt $Audits.Count; $index++) {
      if ($Audits[$index].action -ceq $action) {
        $match = $Audits[$index]
        $cursor = $index
        break
      }
    }
    if ($null -eq $match) {
      throw "Missing ordered audit action: $action"
    }
    if ($match.status -cne 'SUCCESS') {
      throw "Audit action did not succeed: $action status=$($match.status)"
    }
  }
}

function Invoke-ServerlessSmokeTest {
  Assert-CleanCapacity

  $platform = Invoke-PortalRequest -Path '/api/platform-status'
  if ($platform.status -cne 'AVAILABLE' -or -not $platform.creation_allowed) {
    throw "Platform is not ready for smoke creation: status=$($platform.status)"
  }

  $health = Invoke-PortalRequest -Path '/health'
  if ($health.dependencies.firestore.status -cne 'ok') {
    throw "Firestore health is not ok: $($health.dependencies.firestore.status)"
  }

  $serviceName = 'demo-smoke-{0}' -f (Get-Date -Format 'yyyyMMddHHmmss')
  $projectId = $null
  $deletedProject = $null
  try {
    $created = Invoke-PortalRequest -Path '/api/projects' -Method 'POST' -Body @{
      service_name = $serviceName
      environment = 'dev'
      image = 'nginx:latest'
      replicas = 1
      cpu_request = '100m'
      cpu_limit = '500m'
      memory_request = '128Mi'
      memory_limit = '512Mi'
      expose_external = $false
    }
    $projectId = [string]$created.id
    if ([string]::IsNullOrWhiteSpace($projectId)) {
      throw 'Create response did not contain a project id.'
    }

    $running = Wait-ProjectStatus -ProjectId $projectId -ExpectedStatus @('RUNNING')
    $auditResponse = Invoke-PortalRequest -Path "/api/projects/$projectId/audit-logs"
    $audits = @(ConvertTo-PortalArray -Value $auditResponse)
    Assert-AuditSequence -Audits $audits -RequiredActions @(
      'PROJECT_CREATE_REQUESTED',
      'PROJECT_PROVISIONING_STARTED',
      'NAMESPACE_CREATED',
      'RESOURCE_QUOTA_CREATED',
      'DEPLOYMENT_CREATED',
      'SERVICE_CREATED',
      'PROJECT_RUNNING'
    )

    $podResponse = Invoke-PortalRequest -Path "/api/projects/$projectId/pods"
    $pods = @(ConvertTo-PortalArray -Value $podResponse)
    $eventResponse = Invoke-PortalRequest `
      -Path "/api/projects/$projectId/events?limit=20"
    $events = @(ConvertTo-PortalArray -Value $eventResponse)
    $synced = Wait-ProjectSyncStatus -ProjectId $projectId

    [pscustomobject]@{
      BaseUri = $BaseUri
      ProjectId = $projectId
      Namespace = $running.namespace
      PodCount = $pods.Count
      EventCount = $events.Count
      Status = $synced.status
    }
  }
  finally {
    if (-not [string]::IsNullOrWhiteSpace($projectId)) {
      try {
        Invoke-PortalRequest -Path "/api/projects/$projectId" -Method 'DELETE' | Out-Null
        $deletedProject = Wait-ProjectStatus -ProjectId $projectId -ExpectedStatus @('DELETED')
        $deleteAuditResponse = Invoke-PortalRequest -Path "/api/projects/$projectId/audit-logs"
        $deleteAudits = @(ConvertTo-PortalArray -Value $deleteAuditResponse)
        Assert-AuditSequence -Audits $deleteAudits -RequiredActions @(
          'PROJECT_DELETE_REQUESTED',
          'PROJECT_DELETED'
        )
        if ($deletedProject.status -cne 'DELETED') {
          throw "Cleanup did not reach DELETED: $($deletedProject.status)"
        }
        Assert-CleanCapacity
      }
      catch {
        Write-Error "Smoke cleanup failed for project=$projectId. $($_.Exception.Message)"
      }
    }
  }
}

Invoke-ServerlessSmokeTest
