param(
    [string]$ClusterName = "portal-dev"
)

$ErrorActionPreference = "Stop"

Write-Host "Deleting kind cluster '$ClusterName'..."
kind delete cluster --name $ClusterName
Write-Host "kind cluster '$ClusterName' deleted."
