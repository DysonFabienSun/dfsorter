# Shared, checksum-pinned build inputs retained in the DFSorter repository.
function Get-VerifiedDependency {
    param(
        [Parameter(Mandatory)][ValidateSet('libmpv', 'ffmpeg')][string]$Name,
        [Parameter(Mandatory)][string]$Root
    )
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'packaging/dependencies.json') -Raw | ConvertFrom-Json -AsHashtable
    if ($manifest.schema_version -ne 1) { throw 'Unsupported dependency manifest version.' }
    $dependency = $manifest.dependencies[$Name]
    if (-not $dependency -or $dependency.sha256 -notmatch '^[a-f0-9]{64}$' -or
        [System.IO.Path]::GetFileName($dependency.archive) -cne $dependency.archive) {
        throw "Invalid dependency manifest entry: $Name."
    }
    $cache = Join-Path $Root 'cache/dependencies'
    New-Item -ItemType Directory -Force $cache | Out-Null
    $archive = Join-Path $cache $dependency.archive
    if (-not (Test-Path -LiteralPath $archive)) {
        $partial = "$archive.$([guid]::NewGuid().ToString('N')).partial"
        try {
            Invoke-WebRequest -Uri $dependency.url -OutFile $partial
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sha256) {
                throw "$Name archive checksum mismatch."
            }
            Move-Item -LiteralPath $partial -Destination $archive
        } finally {
            if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial }
        }
    }
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.sha256) {
        throw "$Name cached archive checksum mismatch. Remove the invalid archive: $archive"
    }
    $directory = Join-Path $cache "$Name-$($dependency.sha256)"
    # Verify extracted files on every call, including cache hits. An interrupted
    # extraction can be completed safely from the verified archive on retry.
    $complete = $true
    foreach ($relative in $dependency.files.Keys) {
        $path = [System.IO.Path]::GetFullPath((Join-Path $directory $relative))
        $prefix = [System.IO.Path]::GetFullPath($directory) + [System.IO.Path]::DirectorySeparatorChar
        if (-not $path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Dependency file escapes extraction directory: $relative"
        }
        if (-not (Test-Path -LiteralPath $path) -or
            (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.files[$relative]) {
            $complete = $false
        }
    }
    if (-not $complete) {
        Expand-Archive -LiteralPath $archive -DestinationPath $directory -Force
        foreach ($relative in $dependency.files.Keys) {
            $path = Join-Path $directory $relative
            if (-not (Test-Path -LiteralPath $path) -or
                (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependency.files[$relative]) {
                throw "$Name extracted file checksum mismatch: $relative"
            }
        }
    }
    return [pscustomobject]@{ Directory = $directory; Manifest = $dependency }
}
