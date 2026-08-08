<#
.SYNOPSIS
  Downloads portable Prometheus and Grafana into note/observability/, one
  level above both git repos - no Docker, no admin rights, no Windows
  service registration. Idempotent: skips whatever is already extracted.

.DESCRIPTION
  Neither binary is committed to git (Prometheus is ~100MB, Grafana ~350MB
  compressed). This script reproduces them on any laptop the unit migrates
  to. Run once per laptop, then use launch.ps1 every session.
#>

$ErrorActionPreference = "Stop"

# Sibling to both torque/ and mcp-hub/, not inside either - nothing here is
# ever a candidate for `git add`.
$Obs = Resolve-Path (Join-Path $PSScriptRoot "..\..\observability" -ErrorAction SilentlyContinue) `
    -ErrorAction SilentlyContinue
if (-not $Obs) {
    $Obs = Join-Path (Split-Path $PSScriptRoot -Parent | Split-Path -Parent) "observability"
    New-Item -ItemType Directory -Force -Path $Obs | Out-Null
}
Write-Host "Observability binaries -> $Obs"

# --- Prometheus --------------------------------------------------------------
if (Test-Path (Join-Path $Obs "prometheus\prometheus.exe")) {
    Write-Host "Prometheus already present, skipping."
} else {
    Write-Host "Fetching latest Prometheus release..."
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/prometheus/prometheus/releases/latest"
    $asset = $rel.assets | Where-Object { $_.name -match "windows-amd64\.zip$" } | Select-Object -First 1
    if (-not $asset) { throw "No windows-amd64 asset found on the latest Prometheus release." }

    $zip = Join-Path $Obs "prometheus.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Obs "extract") -Force
    $dir = Get-ChildItem (Join-Path $Obs "extract") -Directory | Select-Object -First 1
    Move-Item -Path $dir.FullName -Destination (Join-Path $Obs "prometheus") -Force
    Remove-Item (Join-Path $Obs "extract") -Recurse -Force
    Remove-Item $zip -Force
    Write-Host "Prometheus $($rel.tag_name) extracted."
}

# Scrape config lives in this repo (small text file), copied into place so a
# stale copy from a previous laptop never silently wins.
Copy-Item (Join-Path $PSScriptRoot "prometheus.yml") `
    (Join-Path $Obs "prometheus\prometheus.yml") -Force

# --- Grafana -------------------------------------------------------------
if (Test-Path (Join-Path $Obs "grafana\bin\grafana.exe")) {
    Write-Host "Grafana already present, skipping."
} else {
    # GitHub releases carry source tarballs only; the real binaries live on
    # dl.grafana.com under the same version tag.
    Write-Host "Fetching latest Grafana release..."
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/grafana/grafana/releases/latest"
    $ver = $rel.tag_name.TrimStart("v")
    $url = "https://dl.grafana.com/oss/release/grafana-$ver.windows-amd64.zip"

    $zip = Join-Path $Obs "grafana.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath (Join-Path $Obs "extract") -Force
    $dir = Get-ChildItem (Join-Path $Obs "extract") -Directory | Select-Object -First 1
    Move-Item -Path $dir.FullName -Destination (Join-Path $Obs "grafana") -Force
    Remove-Item (Join-Path $Obs "extract") -Recurse -Force
    Remove-Item $zip -Force
    Write-Host "Grafana $ver extracted."
}

Write-Host ""
Write-Host "Done. Run .\launch.ps1 to start both, or see QUICKSTART.md."
