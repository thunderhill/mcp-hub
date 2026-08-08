<#
.SYNOPSIS
  Starts Prometheus (:9090) and Grafana (:3000) as plain background
  processes - no Windows service registration, so no admin rights needed,
  matching every other unit in this project.

.DESCRIPTION
  All Grafana configuration is passed as environment variables rather than
  baked into a committed ini file, because the one thing that genuinely
  differs per laptop - where the extracted binaries and runtime data live -
  is computed HERE from $PSScriptRoot at launch time. Nothing with an
  absolute path ever gets committed.

  Run setup.ps1 first, once per laptop.
#>

$ErrorActionPreference = "Stop"

$RepoObs = $PSScriptRoot                                          # mcp-hub/observability
$Obs     = Split-Path (Split-Path $RepoObs -Parent) -Parent        # .../note
$Obs     = Join-Path $Obs "observability"                          # .../note/observability

$PromExe = Join-Path $Obs "prometheus\prometheus.exe"
$PromData = Join-Path $Obs "prometheus\data"
$GrafExe = Join-Path $Obs "grafana\bin\grafana.exe"
$GrafHome = Join-Path $Obs "grafana"
$GrafData = Join-Path $Obs "grafana-data"

if (-not (Test-Path $PromExe) -or -not (Test-Path $GrafExe)) {
    Write-Error "Binaries not found under $Obs - run .\setup.ps1 first."
    exit 1
}

New-Item -ItemType Directory -Force -Path $PromData, $GrafData, "$GrafData\logs", "$GrafData\plugins" `
    | Out-Null

# Copy this repo's scrape config into place - always wins over whatever an
# older laptop left behind.
Copy-Item (Join-Path $RepoObs "prometheus.yml") (Join-Path $Obs "prometheus\prometheus.yml") -Force

Write-Host "Starting Prometheus on :9090 ..."
Start-Process -FilePath $PromExe -WorkingDirectory (Join-Path $Obs "prometheus") -WindowStyle Hidden `
    -ArgumentList @(
        "--config.file=prometheus.yml",
        "--storage.tsdb.path=$PromData",
        "--web.listen-address=:9090"
    )

Write-Host "Starting Grafana on :3000 ..."
$env:GF_PATHS_PROVISIONING = Join-Path $RepoObs "provisioning"
$env:GF_PATHS_DATA = $GrafData
$env:GF_PATHS_LOGS = Join-Path $GrafData "logs"
$env:GF_PATHS_PLUGINS = Join-Path $GrafData "plugins"
$env:GF_SERVER_HTTP_PORT = "3000"
$env:GF_SECURITY_ADMIN_USER = "admin"
$env:GF_SECURITY_ADMIN_PASSWORD = "torque2026"
$env:GF_USERS_ALLOW_SIGN_UP = "false"
$env:GF_ANALYTICS_REPORTING_ENABLED = "false"
$env:GF_ANALYTICS_CHECK_FOR_UPDATES = "false"
$env:GF_LOG_MODE = "console"

Start-Process -FilePath $GrafExe -WorkingDirectory $RepoObs -WindowStyle Hidden `
    -ArgumentList @("server", "--homepath=$GrafHome")

Write-Host ""
Write-Host "Waiting for both to come up..."
$ok = $true
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try { $p = (Invoke-WebRequest "http://127.0.0.1:9090/-/healthy" -UseBasicParsing -TimeoutSec 3).StatusCode } catch { $p = 0 }
    try { $g = (Invoke-WebRequest "http://127.0.0.1:3000/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode } catch { $g = 0 }
    if ($p -eq 200 -and $g -eq 200) {
        Write-Host "Prometheus : http://127.0.0.1:9090  (up)"
        Write-Host "Grafana    : http://127.0.0.1:3000  (up)  admin / torque2026"
        Write-Host "Dashboards : TORQUE folder, provisioned automatically"
        exit 0
    }
}
Write-Warning "Timed out waiting for one or both to report healthy. Check $GrafData\logs and the Prometheus console window."
exit 1
