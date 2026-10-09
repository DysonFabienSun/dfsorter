# Windows portable release process

The installation instructions are in `README.md`. This file covers release preparation.

## Build

Run `pwsh -File packaging/build-release.ps1` on Windows with `uv` available. The script installs Python 3.13 and locked build dependencies, verifies the pinned libmpv and FFmpeg archives, builds the application and updater, and writes `build/DFSorter-Windows-x64.zip`. The optional `-NoProxy` switch is used in CI; local builds use the PowerShell profile's proxy helpers when present.

The release build includes `configs/shipped/*.yaml` as game defaults and always includes `configs/tips/*.yaml` as tip defaults. The shipped game files are maintained separately from editable preferences in `configs/games/`; copy selected changes there when they are ready for release. It does not include a catalogue or settings. It bundles `runtime/mpv/`, FFmpeg and ffprobe, Qt plugins, icons, and third-party license files. The bundle's `release.json` lists hashes for every application-owned file. The updater replaces those files after DFSorter exits, while `data/`, `configs/`, `cache/`, and `backups/` stay in the extracted directory.

## Publish

1. Finish and commit all features, fixes, tests, specifications, documentation, and release workflow changes separately from the version preparation commit.
2. Update the version in `pyproject.toml` and run `uv lock`. On a Windows machine where local ZIP builds are permitted, build and extract the ZIP into a fresh writable folder. Launch `DFSorter.exe`, inspect media, play a clip, and exercise Share using the bundled tools.
3. Commit only `pyproject.toml` and `uv.lock` as `Prepare vX.Y.Z release`. Verify that the commit changes only those two files, then push a matching `vX.Y.Z` tag pointing at that commit. The Windows release workflow builds the ZIP from the tagged commit and creates a draft GitHub Release. Only stable releases are used by the in-app update check.

Do not publish a tag until the build is ready: the release workflow uploads its ZIP to the draft automatically. If the workflow fails, fix the build and create a new version tag rather than replacing an already published release.

## Update behavior

Portable copies check GitHub once after startup and when **Settings → Check for updates…** is chosen. The download dialog shows percentage and downloaded/total MB when the size is available, or downloaded MB with an animated bar otherwise. It verifies the release asset's SHA-256 digest during download and again in the updater. The updater verifies the package manifest, waits for the app process to exit, copies `data/` and `configs/` to `backups/updates/`, replaces packaged files, and launches the new EXE. Failed replacement rolls back the packaged files. Locally edited game definitions stay active; changed defaults are copied to `configs/default-updates/` for review.

**Settings → General → Updates → Download source** selects **gh-proxy.org** (default) or **GitHub (direct)**. The selection is saved in `data/settings.yaml` and applies to subsequent downloads. The mirror URL is `https://gh-proxy.org/` followed by the complete GitHub asset URL, for example `https://gh-proxy.org/https://github.com/DysonFabienSun/dfsorter/releases/download/v1.1.2/DFSorter-v1.1.2-Windows-x64.zip`. Version checks still use GitHub directly, and all downloaded ZIPs must match GitHub's SHA-256 digest. The dropdown has no custom URL field.

If downloading fails, the dialog provides a manual download link and the installation folder. Save the ZIP directly beside `DFSorter.exe`, keeping the exact release filename (`DFSorter-vX.Y.Z-Windows-x64.zip`), then run **Check for updates…** again. After a successful version check, both manual and startup checks detect that ZIP and offer verification and installation without downloading again. The local ZIP remains in place. Offline checks and renamed ZIPs are not supported; a failed checksum blocks installation.
