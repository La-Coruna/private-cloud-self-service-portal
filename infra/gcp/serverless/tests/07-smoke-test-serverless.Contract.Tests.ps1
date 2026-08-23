$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot '..\07-smoke-test-serverless.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
  throw 'The serverless smoke-test script does not exist.'
}

$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path -LiteralPath $scriptPath).Path,
  [ref]$tokens,
  [ref]$parseErrors
)
if ($parseErrors.Count -ne 0) {
  throw "PowerShell syntax check failed: $($parseErrors.Message -join '; ')"
}

$source = Get-Content -Raw -LiteralPath $scriptPath
$requiredFunctions = @(
  'Invoke-PortalRequest',
  'ConvertTo-PortalArray',
  'Wait-ProjectStatus',
  'Wait-ProjectSyncStatus',
  'Assert-CleanCapacity',
  'Invoke-ServerlessSmokeTest'
)
foreach ($name in $requiredFunctions) {
  $function = $ast.FindAll({
      param($node)
      $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -ceq $name
    }, $true) | Select-Object -First 1
  if ($null -eq $function) {
    throw "Missing required function: $name"
  }
}

foreach ($requiredText in @(
    'https://private-cloud-portal-demo-2.web.app',
    'demo-smoke-',
    'nginx:latest',
    'dependencies.firestore.status',
    '/pods',
    '/events?limit=20',
    '/sync-status',
    '/audit-logs',
    'PROJECT_CREATE_REQUESTED',
    'PROJECT_RUNNING',
    'PROJECT_DELETED',
    'finally',
    'DELETED'
  )) {
  if (-not $source.Contains($requiredText)) {
    throw "Smoke-test safety contract is missing: $requiredText"
  }
}

$postCalls = ([regex]::Matches($source, "-Method\s+'?POST'?", 'IgnoreCase')).Count
if ($postCalls -gt 2) {
  throw 'The smoke test may issue only one create POST and one sync POST.'
}

Write-Output 'Serverless smoke-test syntax and cleanup contract tests passed.'
