$ErrorActionPreference = 'Stop'

$pythonwPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw 'Python environment missing. Run uv sync --python 3.13 first.'
}

$shortcutPath = Join-Path $PSScriptRoot 'DFSorter.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '-m dfsorter.ui'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Open DFSorter without a console window'
$shortcut.Save()
Write-Output "Created $shortcutPath"
