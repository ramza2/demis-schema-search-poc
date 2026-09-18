param(
    [ValidateSet("deploy", "status", "logs", "down")]
    [string]$Command = "deploy",
    [string]$EnvFile = ".env.lan"
)

$ErrorActionPreference = "Stop"

function Fail([string]$Message) {
    throw $Message
}

function Read-EnvValue([string]$Key) {
    if (-not (Test-Path $EnvFile)) { return $null }
    $line = Get-Content $EnvFile |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Key))=" } |
        Select-Object -Last 1
    if (-not $line) { return $null }
    return (($line -split "=", 2)[1]).Trim().Trim('"').Trim("'")
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Fail "docker is not installed or not on PATH"
}
docker compose version | Out-Null

if (-not (Test-Path $EnvFile)) {
    Fail "missing $EnvFile (copy .env.lan.example to .env.lan)"
}

$composeArgs = @(
    "compose",
    "--env-file", $EnvFile,
    "-f", "docker-compose.yml",
    "-f", "docker-compose.lan.yml"
)

$oracleEnabled = Read-EnvValue "ORACLE_TEST_ENABLED"
if ($oracleEnabled -match "^(?i:true|1|yes)$") {
    $composeArgs += @("--profile", "oracle-test")
}

function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Rest)
    & docker @composeArgs @Rest
    if ($LASTEXITCODE -ne 0) {
        Fail "docker compose command failed: $($Rest -join ' ')"
    }
}

function Get-ServiceContainerId([string]$Service) {
    $id = (& docker @composeArgs ps -q $Service 2>$null)
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($id | Select-Object -First 1)
}

function Get-ContainerState([string]$Id) {
    if (-not $Id) { return "" }
    return (& docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' $Id 2>$null)
}

switch ($Command) {
    "status" {
        Invoke-Compose ps
        exit 0
    }
    "logs" {
        & docker @composeArgs logs -f --tail=200
        exit $LASTEXITCODE
    }
    "down" {
        Invoke-Compose down
        exit 0
    }
}

$lanIp = Read-EnvValue "LAN_BIND_IP"
if (-not $lanIp) {
    Fail "LAN_BIND_IP must be set in $EnvFile. Run ipconfig and use the active adapter IPv4 address."
}

Write-Host "Validating compose config..."
& docker @composeArgs config | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "docker compose config failed" }

Write-Host "Starting LAN stack..."
Invoke-Compose up -d --build --remove-orphans

$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    $backendId = Get-ServiceContainerId "backend"
    $frontendId = Get-ServiceContainerId "frontend"

    $backendOk = (Get-ContainerState $backendId) -eq "healthy"
    $frontendOk = (Get-ContainerState $frontendId) -eq "running"
    $oracleOk = $true

    if ($oracleEnabled -match "^(?i:true|1|yes)$") {
        $oracleId = Get-ServiceContainerId "oracle-test"
        $oracleOk = (Get-ContainerState $oracleId) -eq "healthy"
    }

    if ($backendOk -and $frontendOk -and $oracleOk) {
        break
    }

    Start-Sleep -Seconds 5
}

if ((Get-Date) -ge $deadline) {
    & docker @composeArgs ps
    & docker @composeArgs logs --no-color --tail=150
    Fail "timed out waiting for LAN stack readiness"
}

$frontendPort = Read-EnvValue "FRONTEND_EXTERNAL_PORT"
if (-not $frontendPort) { $frontendPort = "8501" }
$backendPort = Read-EnvValue "BACKEND_EXTERNAL_PORT"
if (-not $backendPort) { $backendPort = "8000" }

Write-Host ""
Write-Host "LAN deployment ready."
Write-Host "Frontend: http://${lanIp}:$frontendPort"
Write-Host "Backend : http://${lanIp}:$backendPort"

if ($oracleEnabled -match "^(?i:true|1|yes)$") {
    Write-Host "Oracle target from Schema Analyzer backend:"
    Write-Host "  host=oracle-test port=1521 service=FREEPDB1 schema=DEMIS_OWNER user=DEMIS_RO"
}

Invoke-Compose ps
