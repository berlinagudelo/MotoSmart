# Prueba de restauración real: restaura el backup en una base temporal,
# consulta una tabla y elimina la base temporal. No toca la base de producción.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Backup,
    [string]$DbHost = $(if ($env:PGHOST) { $env:PGHOST } else { '127.0.0.1' }),
    [int]$Port = $(if ($env:PGPORT) { [int]$env:PGPORT } else { 5432 }),
    [string]$User = $env:PGUSER,
    [switch]$KeepDatabase
)

$ErrorActionPreference = 'Stop'
if (-not $User) { throw 'Define PGUSER o pasa -User.' }
if (-not (Test-Path $Backup)) { throw "No existe el backup: $Backup" }
foreach ($comando in 'createdb', 'dropdb', 'psql', 'pg_restore') {
    if (-not (Get-Command $comando -ErrorAction SilentlyContinue)) {
        throw "$comando no está en PATH."
    }
}

$temporal = "motorsmart_verify_$([Guid]::NewGuid().ToString('N').Substring(0, 10))"
$creada = $false
try {
    Write-Host "Creando base temporal $temporal"
    & createdb --host=$DbHost --port=$Port --username=$User $temporal
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear la base temporal.' }
    $creada = $true

    & pg_restore `
        --host=$DbHost --port=$Port --username=$User --dbname=$temporal `
        --no-owner --no-privileges --exit-on-error $Backup
    if ($LASTEXITCODE -ne 0) { throw 'pg_restore falló en la prueba de restauración.' }

    $resultado = & psql --host=$DbHost --port=$Port --username=$User `
        --dbname=$temporal --tuples-only --no-align `
        --command='SELECT count(*) FROM talleres;'
    if ($LASTEXITCODE -ne 0) { throw 'La consulta de verificación falló.' }
    Write-Host "Restauración verificada. Talleres restaurados: $resultado"
} finally {
    if ($creada -and -not $KeepDatabase) {
        Write-Host "Eliminando base temporal $temporal"
        & dropdb --host=$DbHost --port=$Port --username=$User --if-exists $temporal
    } elseif ($creada) {
        Write-Host "Base temporal conservada: $temporal"
    }
}
