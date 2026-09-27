param([switch]$NoProxy)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
if (-not $IsWindows) { throw 'Windows is required for the portable release build.' }
if (-not $NoProxy -and (Test-Path -LiteralPath $PROFILE)) { . $PROFILE }
$proxyEnabled = -not $NoProxy -and [bool](Get-Command proxyon -ErrorAction SilentlyContinue)
if ($proxyEnabled) { proxyon }
try {
    $versionMatch = Select-String -Path (Join-Path $root 'pyproject.toml') -Pattern '^version = "([0-9]+\.[0-9]+\.[0-9]+)"$' | Select-Object -First 1
    if (-not $versionMatch) { throw 'Project version not found.' }
    $version = $versionMatch.Matches[0].Groups[1].Value
    & uv sync --locked --no-dev --group build --python 3.13
    if ($LASTEXITCODE -ne 0) { throw 'uv sync failed.' }
    if ($root.Contains(',')) {
        # Qt's QLibraryInfo truncates the compiled plugin path at a comma.
        $sitePackages = Join-Path $root '.venv/Lib/site-packages'
        Set-Content -LiteralPath (Join-Path $root '.venv/Scripts/qt.conf') -Value "[Paths]`nPrefix=."
        foreach ($name in @('plugins', 'translations', 'qml')) {
            $link = Join-Path $sitePackages $name
            $target = Join-Path $sitePackages "PySide6/$name"
            if ((Test-Path -LiteralPath $target) -and -not (Test-Path -LiteralPath $link)) {
                New-Item -ItemType Junction -Path $link -Target $target | Out-Null
            }
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $root 'runtime/mpv/libmpv-2.dll'))) {
        & (Join-Path $root 'setup-playback.ps1') -NoProxy
    }
    $ffmpegName = 'ffmpeg-n9.0.2-3-ga5923073bf-win64-gpl-9.0.zip'
    $ffmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-21-13-55/$ffmpegName"
    $ffmpegHash = 'fe372180f20e7f9bfa3d9a481b2b1b98c8296178d8265552608736637ea6b3c8'
    $archive = Join-Path $root "cache/$ffmpegName"
    New-Item -ItemType Directory -Force (Split-Path $archive) | Out-Null
    if (-not (Test-Path -LiteralPath $archive)) { Invoke-WebRequest $ffmpegUrl -OutFile $archive }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ffmpegHash) {
        throw 'FFmpeg archive checksum mismatch.'
    }
    $extracted = Join-Path $root 'cache/ffmpeg-release-extracted'
    Expand-Archive -LiteralPath $archive -DestinationPath $extracted -Force
    $ffmpeg = Get-ChildItem -LiteralPath $extracted -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    $ffprobe = Get-ChildItem -LiteralPath $extracted -Recurse -Filter ffprobe.exe | Select-Object -First 1
    if (-not $ffmpeg -or -not $ffprobe) { throw 'FFmpeg archive lacks ffmpeg.exe or ffprobe.exe.' }

    $dist = Join-Path $root 'build/dist'
    $work = Join-Path $root 'build/pyinstaller'
    $spec = Join-Path $root 'build/spec'
    & uv run --no-sync pyinstaller --noconfirm --clean --onedir --windowed --name DFSorter --icon (Join-Path $root 'resources/mascot/dfsorter.ico') --paths src --distpath $dist --workpath $work --specpath $spec packaging/app_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'App packaging failed.' }
    & uv run --no-sync pyinstaller --noconfirm --clean --onefile --windowed --name DFSorterUpdater --paths src --distpath $dist --workpath $work --specpath $spec packaging/updater_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Updater packaging failed.' }
    $portable = Join-Path $dist 'DFSorter'
    Copy-Item (Join-Path $dist 'DFSorterUpdater.exe') $portable
    Copy-Item (Join-Path $root '.venv/Lib/site-packages/PySide6/plugins') (Join-Path $portable '_internal/PySide6/plugins') -Recurse
    New-Item -ItemType Directory -Force (Join-Path $portable 'resources/mascot'), (Join-Path $portable 'runtime/mpv') | Out-Null
    Copy-Item (Join-Path $root 'resources/icons') (Join-Path $portable 'resources/icons') -Recurse
    Copy-Item (Join-Path $root 'resources/mascot/dfsorter.ico') (Join-Path $portable 'resources/mascot')
    Copy-Item (Join-Path $root 'runtime/mpv/libmpv-2.dll') (Join-Path $portable 'runtime/mpv')
    Copy-Item (Join-Path $root 'runtime/mpv/Copyright') (Join-Path $portable 'runtime/mpv')
    Copy-Item (Join-Path $root 'runtime/mpv/LICENSE.*') (Join-Path $portable 'runtime/mpv')
    New-Item -ItemType Directory -Force (Join-Path $portable 'bin'), (Join-Path $portable 'defaults/games'), (Join-Path $portable 'licenses/ffmpeg'), (Join-Path $portable 'licenses/python-packages') | Out-Null
    Copy-Item $ffmpeg.FullName (Join-Path $portable 'bin/ffmpeg.exe')
    Copy-Item $ffprobe.FullName (Join-Path $portable 'bin/ffprobe.exe')
    Copy-Item (Join-Path $root 'configs/games/*.yaml') (Join-Path $portable 'defaults/games')
    Copy-Item (Join-Path $root 'LICENSE') $portable
    Copy-Item (Join-Path $root 'packaging/THIRD-PARTY-NOTICES.txt') $portable
    Get-ChildItem -LiteralPath $extracted -Recurse -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|COPYRIGHT)' } | ForEach-Object {
        Copy-Item $_.FullName (Join-Path $portable "licenses/ffmpeg/$($_.Name)") -Force
    }
    Get-ChildItem -LiteralPath (Join-Path $root '.venv/Lib/site-packages') -Directory -Filter '*.dist-info' | ForEach-Object {
        $licenses = Get-ChildItem -LiteralPath $_.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|COPYRIGHT|NOTICE)' }
        foreach ($license in $licenses) {
            $destination = Join-Path $portable "licenses/python-packages/$($_.Name)/$($license.Name)"
            New-Item -ItemType Directory -Force (Split-Path $destination) | Out-Null
            Copy-Item $license.FullName $destination -Force
        }
    }
    & uv run --no-sync python packaging/write_manifest.py $portable $version
    if ($LASTEXITCODE -ne 0) { throw 'Release manifest generation failed.' }
    $zip = Join-Path $root 'build/DFSorter-Windows-x64.zip'
    Compress-Archive -LiteralPath $portable -DestinationPath $zip -Force
    Write-Output "Portable release: $zip"
} finally {
    if ($proxyEnabled) { proxyoff }
}
