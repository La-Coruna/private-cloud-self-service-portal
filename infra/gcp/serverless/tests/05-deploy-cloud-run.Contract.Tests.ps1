$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot '..\05-deploy-cloud-run.ps1'
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

function Assert-ThrowsBeforeMutation {
  param([scriptblock]$Action, [string]$Because)

  $dockerBefore = $script:fake.DockerCommands.Count
  $deployBefore = $script:fake.DeployCalls
  try {
    & $Action
  }
  catch {
    Assert-Equal $dockerBefore $script:fake.DockerCommands.Count "$Because; Docker must not mutate"
    Assert-Equal $deployBefore $script:fake.DeployCalls "$Because; Cloud Run must not mutate"
    return
  }

  throw "Expected an exception: $Because"
}

function New-RepositoryJson {
  param(
    [string]$Name = 'portal-demo',
    [string]$Format = 'DOCKER',
    [string]$Location = 'asia-northeast3'
  )

  return ([ordered]@{
    name = "projects/private-cloud-portal-demo-2/locations/$Location/repositories/$Name"
    format = $Format
  } | ConvertTo-Json -Compress)
}

function New-ClusterJson {
  param(
    [bool]$AllowExternalTraffic = $true,
    [bool]$EnableK8sTokensViaDns = $false,
    [bool]$EnableK8sCertsViaDns = $false,
    [bool]$IpEnabled = $true,
    [bool]$EnablePublicEndpoint = $true
  )

  return ([ordered]@{
    name = 'portal-demo-standard'
    location = 'asia-northeast3-a'
    status = 'RUNNING'
    controlPlaneEndpointsConfig = [ordered]@{
      dnsEndpointConfig = [ordered]@{
        allowExternalTraffic = $AllowExternalTraffic
        enableK8sCertsViaDns = $EnableK8sCertsViaDns
        enableK8sTokensViaDns = $EnableK8sTokensViaDns
        endpoint = 'gke-example.asia-northeast3-a.gke.goog'
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
  RepositoryJson = New-RepositoryJson
  RepositoryWritesBenignStderr = $true
  ClusterJson = New-ClusterJson
  GitSha = 'bef16ef'
  DockerCommands = [System.Collections.Generic.List[string]]::new()
  DeployCalls = 0
  DeployArguments = [System.Collections.Generic.List[string]]::new()
}

function git {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)
  $command = ($CommandArgs | ForEach-Object { [string]$_ }) -join ' '
  $global:LASTEXITCODE = 0
  if ($command -eq 'rev-parse --short HEAD') { return $script:fake.GitSha }
  throw "Unexpected git command in contract test: $command"
}

function docker {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)
  $command = ($CommandArgs | ForEach-Object { [string]$_ }) -join ' '
  $script:fake.DockerCommands.Add($command)
  $global:LASTEXITCODE = 0

  $image = 'asia-northeast3-docker.pkg.dev/private-cloud-portal-demo-2/portal-demo/portal-backend:bef16ef'
  if ($command -ceq "build --file backend/Dockerfile --tag $image backend") { return }
  if ($command -ceq "push $image") { return }
  throw "Unexpected Docker command in contract test: $command"
}

function gcloud {
  param([Parameter(ValueFromRemainingArguments = $true)][object[]]$CommandArgs)
  $arguments = @($CommandArgs | ForEach-Object { [string]$_ })
  $command = $arguments -join ' '
  $global:LASTEXITCODE = 0

  if ($command -eq 'config get-value project') { return $script:fake.ActiveProject }
  if ($command -eq 'auth list --filter=status:ACTIVE --format=value(account)') { return $script:fake.ActiveAccount }
  if ($command -eq 'projects describe private-cloud-portal-demo-2 --format=value(projectId)') {
    return 'private-cloud-portal-demo-2'
  }
  if ($command -eq 'artifacts repositories describe portal-demo --location=asia-northeast3 --project=private-cloud-portal-demo-2 --format=json') {
    if ($script:fake.RepositoryWritesBenignStderr) {
      Write-Error 'Encryption: Google-managed key'
    }
    return $script:fake.RepositoryJson
  }
  if ($command -eq 'container clusters describe portal-demo-standard --zone=asia-northeast3-a --project=private-cloud-portal-demo-2 --format=json') {
    return $script:fake.ClusterJson
  }
  if ($command -eq 'auth configure-docker asia-northeast3-docker.pkg.dev --quiet') { return }
  if ($arguments.Count -gt 3 -and ($arguments[0..2] -join ' ') -eq 'run deploy portal-backend') {
    $expected = @(
      'run', 'deploy', 'portal-backend',
      '--project=private-cloud-portal-demo-2', '--region=asia-northeast3',
      '--image=asia-northeast3-docker.pkg.dev/private-cloud-portal-demo-2/portal-demo/portal-backend:bef16ef',
      '--service-account=portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com',
      '--allow-unauthenticated', '--min=0', '--max=2', '--cpu=1', '--memory=512Mi',
      '--concurrency=20', '--timeout=60',
      '--set-env-vars=APP_ENV=production,REPOSITORY_BACKEND=firestore,FIRESTORE_PROJECT_ID=private-cloud-portal-demo-2,FIRESTORE_DATABASE=(default),KUBE_AUTH_MODE=gke,GKE_CLUSTER_LOCATION=asia-northeast3-a,GKE_CLUSTER_NAME=portal-demo-standard,GKE_DNS_ENDPOINT=https://gke-example.asia-northeast3-a.gke.goog,DEMO_MODE=true,DEMO_MAX_PROJECTS=3,DEMO_MAX_REPLICAS=1,DEMO_NAMESPACE_PREFIX=demo-,INGRESS_BASE_DOMAIN=apps.la-coruna.xyz,APP_INGRESS_CLASS_NAME=nginx',
      '--quiet'
    )
    Assert-Equal ($expected -join "`n") ($arguments -join "`n") 'the deployment must use the exact approved Cloud Run contract'
    $script:fake.DeployCalls++
    $script:fake.DeployArguments.Clear()
    $arguments | ForEach-Object { $script:fake.DeployArguments.Add($_) }
    return
  }
  if ($command -eq 'run services describe portal-backend --project=private-cloud-portal-demo-2 --region=asia-northeast3 --format=json') {
    return ([ordered]@{
      metadata = [ordered]@{ name = 'portal-backend' }
      spec = [ordered]@{ template = [ordered]@{ spec = [ordered]@{
        serviceAccountName = 'portal-cloud-run@private-cloud-portal-demo-2.iam.gserviceaccount.com'
      } } }
      status = [ordered]@{
        latestReadyRevisionName = 'portal-backend-00001-test'
        url = 'https://portal-backend.example.invalid'
      }
    } | ConvertTo-Json -Depth 8 -Compress)
  }

  throw "Unexpected gcloud command in contract test: $command"
}

$first = @(Invoke-CloudRunDeployment `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredRegion 'asia-northeast3' `
  -RequiredRepository 'portal-demo' `
  -RequiredClusterName 'portal-demo-standard' `
  -RequiredZone 'asia-northeast3-a' `
  -RequiredAccount 'yougood260807@gmail.com')
Assert-Equal 1 $script:fake.DeployCalls 'the valid contract should deploy once'
Assert-Equal 'imageTag=bef16ef' $first[0] 'the deployed image tag must come from the immutable HEAD SHA'
Assert-Equal 'revision=portal-backend-00001-test' $first[1] 'the result should expose the verified ready revision'
Assert-Equal 'url=https://portal-backend.example.invalid' $first[2] 'the result should expose the public service URL'

$second = @(Invoke-CloudRunDeployment `
  -RequiredProjectId 'private-cloud-portal-demo-2' `
  -RequiredRegion 'asia-northeast3' `
  -RequiredRepository 'portal-demo' `
  -RequiredClusterName 'portal-demo-standard' `
  -RequiredZone 'asia-northeast3-a' `
  -RequiredAccount 'yougood260807@gmail.com')
Assert-Equal 2 $script:fake.DeployCalls 'a repeat run should safely reconcile the same immutable image and settings'
Assert-Equal 'imageTag=bef16ef' $second[0] 'a repeat run must preserve the immutable tag'

$script:fake.ActiveAccount = 'itsokay260617@gmail.com'
Assert-ThrowsBeforeMutation -Because 'the previous deployment account must be rejected' -Action {
  Invoke-CloudRunDeployment `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredRegion 'asia-northeast3' `
    -RequiredRepository 'portal-demo' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}
$script:fake.ActiveAccount = 'yougood260807@gmail.com'

$script:fake.RepositoryJson = New-RepositoryJson -Format 'MAVEN'
Assert-ThrowsBeforeMutation -Because 'a non-Docker repository must be rejected' -Action {
  Invoke-CloudRunDeployment `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredRegion 'asia-northeast3' `
    -RequiredRepository 'portal-demo' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}
$script:fake.RepositoryJson = New-RepositoryJson

$script:fake.ClusterJson = New-ClusterJson -AllowExternalTraffic $false
Assert-ThrowsBeforeMutation -Because 'an externally disabled GKE DNS endpoint must be rejected' -Action {
  Invoke-CloudRunDeployment `
    -RequiredProjectId 'private-cloud-portal-demo-2' `
    -RequiredRegion 'asia-northeast3' `
    -RequiredRepository 'portal-demo' `
    -RequiredClusterName 'portal-demo-standard' `
    -RequiredZone 'asia-northeast3-a' `
    -RequiredAccount 'yougood260807@gmail.com'
}

Write-Output 'Cloud Run deployment command and safety contract tests passed.'
