# Windows portable release process

The installation instructions are in `README.md`. This file covers release preparation.

## Build

Run `pwsh -File packaging/build-release.ps1` on Windows with `uv` available. The script installs Python 3.13 and locked build dependencies, verifies the pinned libmpv and FFmpeg archives, builds the application and updater, and writes `build/DFSorter-Windows-x64.zip`. The optional `-NoProxy` switch is used in CI; local builds use the PowerShell profile's proxy helpers when present.

The release build includes the current `configs/games/*.yaml` as defaults. It does not include a catalogue or settings. It bundles `runtime/mpv/`, FFmpeg and ffprobe, Qt plugins, icons, and third-party license files. The bundle's `release.json` lists hashes for every application-owned file. The updater replaces those files after DFSorter exits, while `data/`, `configs/`, `cache/`, and `backups/` stay in the extracted directory.

## Publish

1. Update the version in `pyproject.toml`, then run `uv lock` and commit the change.
2. Build locally and extract the ZIP into a fresh writable folder. Launch `DFSorter.exe`, inspect media, play a clip, and exercise Share using the bundled tools.
3. Push a matching `vX.Y.Z` tag. The Windows release workflow builds the ZIP from the tagged commit and publishes a public GitHub Release. Only stable releases are used by the in-app update check.

Do not publish a tag until the build is ready: the release workflow publishes its ZIP automatically. If the workflow fails, fix the build and create a new version tag rather than replacing an already published release.

## Update behavior

The app checks GitHub only when **Settings → Check for updates…** is chosen. It verifies the release asset's SHA-256 digest during download and again in the updater. The updater verifies the package manifest, waits for the app process to exit, copies `data/` and `configs/` to `backups/updates/`, replaces packaged files, and launches the new EXE. Failed replacement rolls back the packaged files. Locally edited game definitions stay active; changed defaults are copied to `configs/default-updates/` for review.
