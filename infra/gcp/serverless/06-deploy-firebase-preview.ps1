[CmdletBinding()]
param(
  [string]$ProjectId = 'private-cloud-portal-demo-2',
  [string]$ExpectedAccount = 'yougood260807@gmail.com'
)

$ErrorActionPreference = 'Stop'
$script:approvedProjectId = 'private-cloud-portal-demo-2'
$script:approvedAccount = 'yougood260807@gmail.com'
$script:firebaseCli = Join-Path $env:APPDATA 'npm/node_modules/firebase-tools/lib/bin/firebase.js'

function Invoke-FirebaseCli {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
  & npx.cmd --yes --package=node@20 -- node $script:firebaseCli @Arguments
}


function Assert-ApprovedContext {
  if ($ProjectId -cne $script:approvedProjectId) {
    throw 'The requested Firebase project is not the approved migration project.'
  }
  if ($ExpectedAccount -cne $script:approvedAccount) {
    throw 'The requested Firebase account is not the approved new deployment account.'
  }

  foreach ($command in @('npx.cmd', 'npm')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
      throw "Required command is unavailable: $command"
    }
  }
  if (-not (Test-Path -LiteralPath $script:firebaseCli)) {
    throw 'The installed Firebase CLI entry point is unavailable.'
  }

  $loginOutput = (Invoke-FirebaseCli login:list 2>$null) -join [Environment]::NewLine
  if ($LASTEXITCODE -ne 0 -or
      $loginOutput.Trim() -cne "Logged in as $ExpectedAccount") {
    throw 'The active Firebase account does not match the approved new deployment account.'
  }

  $previousErrorActionPreference = $ErrorActionPreference
  try {
    $ErrorActionPreference = 'Continue'
    $projectResult = (Invoke-FirebaseCli projects:list --json 2>$null) -join [Environment]::NewLine
    $projectExitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($projectExitCode -ne 0) {
    throw 'Could not list Firebase projects.'
  }
  try {
    $projects = $projectResult | ConvertFrom-Json
  }
  catch {
    throw 'Firebase project inventory returned malformed JSON.'
  }
  $project = @($projects.result) |
    Where-Object { $_.projectId -ceq $ProjectId } |
    Select-Object -First 1
  if ($null -eq $project -or $project.state -cne 'ACTIVE' -or
      $project.resources.hostingSite -cne $ProjectId) {
    throw 'The approved Firebase project or default Hosting site is unavailable.'
  }
}

function Assert-HostingConfiguration {
  $firebaseRc = Get-Content -Raw -LiteralPath '.firebaserc' | ConvertFrom-Json
  if ($firebaseRc.projects.default -cne $ProjectId) {
    throw '.firebaserc does not select the approved Firebase project.'
  }

  $configuration = Get-Content -Raw -LiteralPath 'firebase.json' | ConvertFrom-Json
  if ($configuration.hosting.public -cne 'frontend/dist') {
    throw 'Firebase Hosting public output is not frontend/dist.'
  }

  $rewrites = @($configuration.hosting.rewrites)
  if ($rewrites.Count -ne 2) {
    throw 'Firebase Hosting must contain exactly two ordered rewrites.'
  }
  if ($rewrites[0].regex -cne '^/(api/.*|health)$' -or
      $rewrites[0].run.serviceId -cne 'portal-backend' -or
      $rewrites[0].run.region -cne 'asia-northeast3' -or
      $rewrites[0].run.pinTag -isnot [bool] -or
      -not $rewrites[0].run.pinTag) {
    throw 'The first Firebase rewrite must pin API and health paths to the approved Cloud Run service.'
  }
  if ($rewrites[1].source -cne '**' -or
      $rewrites[1].destination -cne '/index.html') {
    throw 'The final Firebase rewrite must be the SPA fallback.'
  }
}

function Invoke-FrontendVerification {
  Push-Location 'frontend'
  try {
    & npm test -- --run
    if ($LASTEXITCODE -ne 0) {
      throw 'Frontend tests failed.'
    }
    & npm run lint
    if ($LASTEXITCODE -ne 0) {
      throw 'Frontend lint failed.'
    }
    & npm run build
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path 'dist/index.html')) {
      throw 'Frontend production build failed.'
    }
  }
  finally {
    Pop-Location
  }
}

Assert-ApprovedContext
Assert-HostingConfiguration
Invoke-FrontendVerification

Invoke-FirebaseCli use $ProjectId
if ($LASTEXITCODE -ne 0) {
  throw 'Could not select the approved Firebase project.'
}
Invoke-FirebaseCli deploy --only hosting --project $ProjectId --non-interactive
if ($LASTEXITCODE -ne 0) {
  throw 'Firebase Hosting deployment failed.'
}

Write-Output "project=$ProjectId"
Write-Output "url=https://$ProjectId.web.app"
