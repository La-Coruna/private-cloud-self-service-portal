param(
    [string]$ClusterName = "portal-dev",
    [string]$ConfigPath = "infra/kind/kind-config.yaml"
)

$ErrorActionPreference = "Stop"

if (kind get clusters | Where-Object { $_ -eq $ClusterName }) {
    Write-Host "kind cluster '$ClusterName' already exists."
    Write-Host "If host port mappings changed, run infra/scripts/delete-kind-cluster.ps1 first."
} else {
    Write-Host "Creating kind cluster '$ClusterName' with $ConfigPath..."
    kind create cluster --name $ClusterName --config $ConfigPath
}

kubectl cluster-info --context "kind-$ClusterName"
kubectl get nodes
