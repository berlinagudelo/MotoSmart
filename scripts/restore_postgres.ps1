# Restaura un backup de MotoSmart en una base PostgreSQL.
# Por seguridad exige -Confirmar y nunca restaura sobre una base con conexiones
# activas de la aplicación.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [Parameter(Mandatory = $true)][string]$Database,
    [string]$DbHost = $(if ($env:PGHOST) { $env:PGHOST } else { '127.0.0.1' }),
    [int]$Port = $(if ($env:PGPORT) { [int]$env:PGPORT } else { 5432 }),
    [string]$User = $env:PGUSER,
    [switch]$Confirmar
)

$ErrorActionPreference = 'Stop'
if (-not $Confirmar) {
    throw 'La restauración sobrescribe datos. Repite con -Confirmar.'
}
if (-not $User) { throw 'Define PGUSER o pasa -User.' }
if (-not (Test-Path $Backup)) { throw "No existe el backup: $Backup" }

$hashPath = "$Backup.sha256"
if (Test-Path $hashPath) {
    $esperado = (Get-Content $hashPath -TotalCount 1).Split(' ')[0].ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 -Path $Backup).Hash.ToLower()
    if ($esperado -ne $actual) { throw 'El checksum SHA256 del backup no coincide.' }
    Write-Host 'Checksum verificado.'
}

Write-Host "Restaurando $Backup en $Database"
& pg_restore `
    --host=$DbHost --port=$Port --username=$User --dbname=$Database `
    --clean --if-exists --no-owner --no-privileges --exit-on-error `
    $Backup
if ($LASTEXITCODE -ne 0) { throw "pg_restore falló con código $LASTEXITCODE." }
Write-Host 'Restauración completada. Ejecuta las migraciones pendientes con: alembic upgrade head'
