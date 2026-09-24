$ErrorActionPreference = 'Stop'

$venvConfigPath = Join-Path $PSScriptRoot '.venv\pyvenv.cfg'
if (-not (Test-Path -LiteralPath $venvConfigPath)) {
    throw 'Python environment missing. Run uv sync --python 3.13 first.'
}

$pythonHome = Get-Content -LiteralPath $venvConfigPath |
    Where-Object { $_ -match '^home\s*=\s*(.+)$' } |
    ForEach-Object { $Matches[1].Trim() } |
    Select-Object -First 1
if (-not $pythonHome) {
    throw 'Python environment configuration has no home interpreter.'
}

$pythonwPath = Join-Path $pythonHome 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonwPath)) {
    throw "GUI Python interpreter missing at $pythonwPath."
}

$shortcutPath = Join-Path $PSScriptRoot 'DFSorter.lnk'
$shellObject = New-Object -ComObject WScript.Shell
$shortcut = $shellObject.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonwPath
$shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'launch.pyw') + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = 'Open DFSorter without a console window'
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'resources\mascot\dfsorter.ico') + ',0'
$shortcut.Save()
Write-Output "Created $shortcutPath"
