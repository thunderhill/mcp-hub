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

# grafana.exe carries its own explicit Windows Firewall BLOCK rule, so the
# only way it is LAN-reachable is proxied through the TORQUE API on :8100
# (app/api/grafana_proxy.py), same trick as the Next.js dashboards. Grafana
# has to be told it's served from a sub-path so it emits "/grafana/..."
# asset and API links instead of root-relative ones.
$env:GF_SERVER_ROOT_URL = "http://127.0.0.1:8100/grafana/"
$env:GF_SERVER_SERVE_FROM_SUB_PATH = "true"
# root_url's host is loopback (only the /grafana/ sub-path actually matters
# for link generation), but real access is over the LAN IP through the
# proxy. Grafana's [live] section governs this, not [security] - "origin not
# allowed" comes from allowed_origins (GF_LIVE_ALLOWED_ORIGINS): "If not set
# then origin will be matched over root_url", which only has ONE host baked
# in, so every request whose Origin differs from root_url's 403s, including
# plain REST API calls, not just the WebSocket "Live" feature the setting is
# named for. There is no [security] csrf_trusted_origins in this version -
# that name doesn't exist in defaults.ini and setting it is a silent no-op.
#
# Detected fresh at every launch, same reasoning as the rest of this project:
# no LAN IP ever gets baked into a committed file, since DHCP can hand out a
# new one.
$lanIps = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" }).IPAddress
$origins = @("http://127.0.0.1:8100", "http://localhost:8100") + ($lanIps | ForEach-Object { "http://$_`:8100" })
$env:GF_LIVE_ALLOWED_ORIGINS = ($origins -join ",")
Write-Host "Grafana allowed origins: $($env:GF_LIVE_ALLOWED_ORIGINS)"

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
