<#
Helper script to build and run the Docker image on Windows PowerShell.
Usage: .\run_docker.ps1
#>

Write-Host "Checking Docker availability..."
try {
    docker version --format '{{.Server.Version}}' 2>$null | Out-Null
} catch {
    Write-Host "Docker does not appear to be available. Ensure Docker Desktop is running." -ForegroundColor Red
    exit 1
}

Write-Host "Listing local images (filter: salary-gateway)..."
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}" | Select-String "salary-gateway" -Quiet
docker images | Where-Object { $_ -match "salary-gateway" } | Out-String

Write-Host "Building image 'salary-gateway' from current directory..."
$build = docker build -t salary-gateway . 2>&1
Write-Host $build
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker build failed. Copy the output above and share it for debugging." -ForegroundColor Red
    exit $LASTEXITCODE
}

$pwd = (Get-Location).Path
Write-Host "Running container (attached) on port 8000 with host mount $pwd..."
try {
    docker run --rm -p 8000:8000 -v "$pwd:/app" -w /app --name salary-gateway-run salary-gateway
} catch {
    Write-Host "Failed to start container. Check for port conflicts or permission issues." -ForegroundColor Red
    exit 1
}
