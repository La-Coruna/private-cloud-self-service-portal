param(
  [string]$BaseUrl = "",
  [int]$WaitSeconds = 300
)

if (-not $BaseUrl) {
  $deadline = (Get-Date).AddSeconds($WaitSeconds)
  do {
    $ip = kubectl -n portal-system get ingress portal-demo -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>$null
    if ($ip) { $BaseUrl = "http://$ip"; break }
    Start-Sleep -Seconds 10
  } while ((Get-Date) -lt $deadline)
}

if (-not $BaseUrl) {
  throw "Ingress IP was not assigned within $WaitSeconds seconds."
}

Write-Host "Smoke testing $BaseUrl"
Invoke-RestMethod "$BaseUrl/health"
Invoke-RestMethod "$BaseUrl/api/projects"
Write-Host "Open demo: $BaseUrl/projects"
