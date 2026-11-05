param([switch]$NoProxy)
$ErrorActionPreference = 'Stop'
if (-not $NoProxy -and (Test-Path -LiteralPath $PROFILE)) { . $PROFILE }
$proxyEnabled = -not $NoProxy -and [bool](Get-Command proxyon -ErrorAction SilentlyContinue)
if ($proxyEnabled) { proxyon }
try {
    . (Join-Path $PSScriptRoot 'packaging/dependencies.ps1')
    $dependency = Get-VerifiedDependency -Name libmpv -Root $PSScriptRoot
    $runtime = Join-Path $PSScriptRoot 'runtime/mpv'
    New-Item -ItemType Directory -Force $runtime | Out-Null
    foreach ($relative in $dependency.Manifest.files.Keys) {
        $target = Join-Path $runtime ([System.IO.Path]::GetFileName($relative))
        if ((Test-Path -LiteralPath $target) -and
            (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -eq $dependency.Manifest.files[$relative]) {
            continue
        }
        Copy-Item -LiteralPath (Join-Path $dependency.Directory $relative) -Destination $target -Force
    }
} finally {
    if ($proxyEnabled) { proxyoff }
}
