param(
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
if ($Tag -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
    throw "Invalid release tag: $Tag."
}
$tagRef = "refs/tags/$Tag"
$objectType = git cat-file -t $tagRef
if ($LASTEXITCODE -ne 0 -or $objectType -ne 'tag') {
    throw "Release $Tag requires an annotated tag containing the proposed changelog."
}
$lines = git for-each-ref '--format=%(contents)' $tagRef
if ($LASTEXITCODE -ne 0) { throw "Cannot read release notes from $Tag." }
$notes = ($lines -join "`n").TrimEnd() + "`n"
if ($notes.Split("`n")[0] -cne "## DFSorter $Tag Changelog") {
    throw "Tag annotation must begin with '## DFSorter $Tag Changelog'."
}
if ($notes -notmatch '(?m)^### .+\n(?:\n)*- \S') {
    throw 'Release notes require a category heading followed by changelog bullets.'
}
if ($notes -notmatch "(?m)^Full Changelog: https://github\.com/[^/\s]+/[^/\s]+/compare/v[0-9]+\.[0-9]+\.[0-9]+\.\.\.$([regex]::Escape($Tag))\s*$") {
    throw "Release notes require a Full Changelog comparison link ending at $Tag."
}
[System.IO.File]::WriteAllText(
    $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath),
    $notes,
    [System.Text.UTF8Encoding]::new($false)
)
