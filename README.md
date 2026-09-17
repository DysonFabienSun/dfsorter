# DFSorter

A Windows desktop catalogue for reviewing gameplay clips without modifying original media.

## Run

Install [uv](https://docs.astral.sh/uv/) and run from this checkout:

```powershell
uv sync --python 3.13
uv run dfsorter
```

After setup, double-click `launch.bat`. The launcher uses its own directory regardless of where it is invoked. Qt's packaged FFmpeg backend decodes H.264 and AV1 MP4 without a separate codec pack. `ffprobe` on PATH enables duration and source-media capture-time inspection; scanning still works without it. `ffmpeg` on PATH is needed only to generate playback test fixtures.

On this machine, dependency downloads use the PowerShell profile's proxy helpers: enable `proxy_on` / `proxyon` before `uv sync` and disable `proxy_off` / `proxyoff` in `finally` afterward.

## Review workflow

1. **Import:** add an external capture folder, choose automatic classification or a forced game, inspect the preview, and confirm. Refresh/rescan is manual.
2. **Session:** search/filter/sort the library and freeze selected clips, the first N, or all results into a session. Editing resumes its saved position after restart.
3. **Editing:** enter metadata such as `1v4 3k jett vandal R4 -- clutch of the century -- clean start`. Enter applies a patch; Shift+Enter also keeps and advances unless already discarded. Empty-command Backspace discards without advancing.
4. **Projects:** activate a project to receive clips when they transition to Keep. Membership survives later triage changes. Add/remove selected clips explicitly when needed.
5. **Export:** select a project, resolve every listed blocker, choose filename fields and an output folder, then copy. Share copies one whole clip independently of project validation.

Space holds playback at 3× when a text field is not consuming the key; releasing restores the previous playback state. The empty command bar allows this shortcut. I/O set range markers outside text controls. In remains pending until a valid Out is set. Stored ranges do not trim video.

Description saves when leaving its editor or navigating, and has an explicit Save button. Rating and triage are independent. Ctrl+Z/Ctrl+Y undo/redo catalogue edits for the current run. Changing game requires confirmation and clears game-specific metadata; Undo restores it.

## Configuration and search

Edit `configs/games/*.yaml`, then use **Config → Reload configurations**. Enum aliases resolve to canonical capitalization. Free-form prefixes support quoted values, for example `wpn:"M4A1 SOPMOD"`. Multiword enum names may be quoted or entered directly. Mainline and description retain the exact text between separators, including spaces. Removing YAML fields hides their stored values; restoring the stable field key restores access.

Queries include `game:val agent:jett`, `triage:keep kill:>=4`, and `technical_condition:LOW_FPS`. Quote multiword query values: `game:"Escape from Tarkov"`. Plain words search filename, mainline, and description. Rating queries are deliberately rejected. Use the triage dropdown to include discarded clips, which are otherwise hidden.

New game definitions receive a reserved scalar `kill` field by default. Ordinary fields are `enum` or `freeform`, optionally `multiple: true`. VALORANT requires agent and weapon for export; Battlefield 6 and Escape from Tarkov have no default required fields. Kept clips with no configured game block export.

## Storage and safety

- `data/dfsorter.db`: SQLite catalogue, projects, capture folders, and session.
- `data/settings.yaml`: default sharing/export destinations.
- `data/dfsorter.log`: rotating operational error log.
- `cache/verification/`: screenshots produced by GUI tests.

These paths are application-local and ignored by Git. Capture paths remain external references. To back up, close DFSorter and copy `data/` and `configs/`. Restore with the application closed; never replace an open database. Moving the application directory preserves its state; moving footage requires **Import → Migrate source folder**.

Missing media remains catalogued. Removing a folder only disables its future discovery. The separate confirmed purge removes catalogue records and relationships, never source files. Migration changes paths atomically and rejects identity collisions.

Share/export preserve original bytes and extensions, sanitize only copied names, and never overwrite existing destinations. Capture folders cannot be output destinations. Existing copies are unmanaged. Cancellation removes the current incomplete copy and sidecar; completed copies remain and are reported. Exported XMP preserves clip ID and In/Out milliseconds in a DFSorter namespace; automatic Premiere interpretation is not claimed.

## Verification

```powershell
uv run pytest -q -p no:faulthandler
uv run ruff check src tests
uv run ruff format --check src tests
```

GUI tests open temporary windows and use disposable catalogues, never the working catalogue. They generate H.264/AV1 media, check decoded frames/audio/seek behavior, and capture normal/maximized windows. Windows can emit a handled COM exception through Python's faulthandler while creating a Qt window; the command above avoids that misleading diagnostic.

Home and Config are intentionally lightweight. Automatic folder polling, an installer, a graphical schema editor, video editing, and Premiere-specific XMP interpretation are outside this v1 delivery. Source inspection and copying run in a background worker; cancellation waits for the current ffprobe call (up to 20 seconds). Library search currently evaluates catalogue rows in memory.
