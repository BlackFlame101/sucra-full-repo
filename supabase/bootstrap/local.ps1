param(
    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl
)
$ErrorActionPreference = "Stop"
$endpoint = [uri]$DatabaseUrl
if ($endpoint.Scheme -notin @("postgres", "postgresql") -or $endpoint.Host -notin @("localhost", "127.0.0.1", "[::1]") -or $endpoint.Port -lt 1) {
    throw "Use an explicit loopback PostgreSQL URL for a disposable Supabase instance."
}
$root = Split-Path -Parent $PSScriptRoot
$files = @(Join-Path $PSScriptRoot "core.sql") + @(
    Get-ChildItem -LiteralPath (Join-Path $root "migrations") -Filter *.sql | Sort-Object Name | ForEach-Object FullName
)
$psqlArguments = @($DatabaseUrl, "-X", "-v", "ON_ERROR_STOP=1", "--single-transaction")
foreach ($file in $files) { $psqlArguments += @("-f", $file) }
& psql @psqlArguments
if ($LASTEXITCODE -ne 0) { throw "Socra schema bootstrap failed." }
foreach ($fixture in (Get-ChildItem -LiteralPath (Join-Path $root "tests") -Filter *.sql | Sort-Object Name)) {
    & psql $DatabaseUrl -X -v ON_ERROR_STOP=1 -f $fixture.FullName
    if ($LASTEXITCODE -ne 0) { throw "SQL fixture failed: $($fixture.Name)" }
}
