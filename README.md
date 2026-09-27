# DFSorter

DFSorter is a portable Windows app for reviewing gameplay recordings. It catalogues clips, helps organize them into projects, and can share selected ranges or copy project clips for export. Original recordings stay in their existing folders.

## Install

1. Download `DFSorter-Windows-x64.zip` from [Releases](https://github.com/DysonFabienSun/dfsorter/releases).
2. In **Extract All**, choose a writable destination such as `C:\Users\<name>`. The ZIP creates a `DFSorter` folder there. Keep that folder together; do not move `DFSorter.exe` out of it.
3. Double-click `DFSorter.exe`, then add capture folders in the app.

No Git, Python, `uv`, FFmpeg, or 7-Zip installation is required. An unsigned release may show a Windows SmartScreen prompt on first launch.

## Update

Choose **Settings → Check for updates…** in DFSorter. If a newer release is available, confirm the update. DFSorter closes, updates its files, and reopens. Update backups are kept in `backups\updates\` inside the extracted folder.

The catalogue, settings, and editable game definitions remain in that folder under `data\` and `configs\games\`. Updates preserve edited definitions; revised defaults appear in `configs\default-updates\`. Capture recordings stay in their original locations. To move or back up DFSorter, close it first and copy the whole extracted folder.
