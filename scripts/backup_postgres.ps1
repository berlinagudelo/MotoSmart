# Backup lógico de PostgreSQL para MotoSmart.
# Requiere pg_dump en PATH. No escribas contraseñas en este archivo:
# usa PGPASSWORD, ~/.pgpass o el servicio de secretos del sistema.
[CmdletBinding()]
param(
    [string]$OutputDir = $(if ($env:MOTOSMART_BACKUP_DIR) { $env:MOTOSMART_BACKUP_DIR } else { Join-Path $PSScriptRoot '..\backups' }),
    [string]$Database = $env:PGDATABASE,
    [string]$DbHost = $(if ($env:PGHOST) { $env:PGHOST } else { '127.0.0.1' }),
    [int]$Port = $(if ($env:PGPORT) { [int]$env:PGPORT } else { 5432 }),
    [string]$User = $env:PGUSER,
    [int]$RetentionDays = 30,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'

if (-not $Database) { throw 'Define PGDATABASE o pasa -Database.' }
if (-not $User) { throw 'Define PGUSER o pasa -User.' }
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw 'pg_dump no está en PATH. Instala PostgreSQL Client Tools.'
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$baseName = "motorsmart-$Database-$stamp"
$dumpPath = Join-Path $OutputDir "$baseName.dump"
$hashPath = "$dumpPath.sha256"

Write-Host "Creando backup de $Database en $dumpPath"
& pg_dump `
    --host=$DbHost --port=$Port --username=$User --dbname=$Database `
    --format=custom --compress=9 --no-owner --no-privileges `
    --file=$dumpPath
if ($LASTEXITCODE -ne 0) { throw "pg_dump falló con código $LASTEXITCODE." }

$hash = Get-FileHash -Algorithm SHA256 -Path $dumpPath
"$($hash.Hash.ToLower())  $baseName.dump" | Set-Content -Encoding ASCII -Path $hashPath
Write-Host "SHA256: $($hash.Hash)"

if (-not $SkipVerify) {
    & pg_restore --list $dumpPath | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'El archivo de backup no se puede leer con pg_restore.' }
    Write-Host 'Backup verificado: pg_restore puede leer el archivo.'
}

$limite = (Get-Date).AddDays(-[Math]::Max(1, $RetentionDays))
Get-ChildItem -Path $OutputDir -Filter 'motorsmart-*.dump*' -File |
    Where-Object { $_.LastWriteTime -lt $limite } |
    ForEach-Object {
        Write-Host "Eliminando backup antiguo: $($_.Name)"
        Remove-Item -Force $_.FullName
    }

Write-Host "Backup completado: $dumpPath"
Write-Output $dumpPath
