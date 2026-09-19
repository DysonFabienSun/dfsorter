$ErrorActionPreference = 'Stop'
. $PROFILE
proxyon
try {
    $runtime = Join-Path $PSScriptRoot 'runtime/mpv'
    $archive = Join-Path $PSScriptRoot 'cache/mpv-dev-20260903.7z'
    New-Item -ItemType Directory -Force $runtime, (Split-Path $archive) | Out-Null
    $url = 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20260903/mpv-dev-x86_64-20260903-git-69e63f425a.7z'
    $expected = 'fac135c68a35b7639e39d72c0c365104edbaebdea39a0dfdd8c36e8c8e80faef'
    if (-not (Test-Path -LiteralPath $archive)) {
        Invoke-WebRequest $url -OutFile $archive
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
        throw 'libmpv archive checksum mismatch'
    }
    $sevenZip = 'C:/Program Files/7-Zip/7z.exe'
    if (-not (Test-Path -LiteralPath $sevenZip)) {
        $sevenZip = (Get-Command 7z -ErrorAction Stop).Source
    }
    & $sevenZip x $archive "-o$runtime" -y
    if ($LASTEXITCODE -ne 0) { throw 'libmpv extraction failed' }
    foreach ($name in @('Copyright', 'LICENSE.GPL', 'LICENSE.LGPL')) {
        Invoke-WebRequest "https://raw.githubusercontent.com/mpv-player/mpv/69e63f425a/$name" -OutFile (Join-Path $runtime $name)
    }
} finally {
    proxyoff
}
