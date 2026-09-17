# DFSorter

A Windows desktop catalogue for reviewing gameplay clips without modifying original media.

## Run

Install [uv](https://docs.astral.sh/uv/) and run from this checkout:

```powershell
uv sync --python 3.13
uv run dfsorter
```

After setup, double-click `launch.bat`. The launcher uses its own directory regardless of where it is invoked. Qt's packaged FFmpeg backend decodes H.264 and AV1 MP4 without a separate codec pack. `ffprobe` on PATH enables duration and source-media capture-time inspection; scanning still works without it. Share requires both `ffmpeg` and `ffprobe` on PATH. The external tools are also used to generate playback test fixtures.

On this machine, dependency downloads use the PowerShell profile's proxy helpers: enable `proxy_on` / `proxyon` before `uv sync` and disable `proxy_off` / `proxyoff` in `finally` afterward.

## Review workflow

1. **Import:** add an external capture folder, choose automatic classification or a forced game, inspect the preview, and confirm. Enabled folders are automatically rescanned on startup; manual Refresh/rescan remains available.
2. **Session:** search/filter/sort the library and freeze selected clips, the first N, or all results into a session. Editing resumes its saved position after restart.
3. **Editing:** starts in review mode. Press `/` or Enter to enter metadata such as `1v4 3k jett vandal R4 -- clutch of the century -- clean start`. In input mode, Enter submits the command and returns to review without changing triage. In review mode, Shift+Enter keeps and advances when the configured game's required fields are present, or advances an explicitly discarded clip without changing its verdict. Shift+Enter never submits, is unavailable in input mode, and refuses advancement while the command bar contains text. Submit that text with Enter first. Escape preserves unfinished text; drafts survive clip/panel navigation for this run. Backspace rejects only in review mode. At the final clip, a legal verdict is applied and Session complete is reported.
4. **Projects:** activate a project to receive clips when they transition to Keep. Membership survives later triage changes. Add/remove selected clips explicitly when needed.
5. **Export:** select a project, resolve every listed blocker, choose filename fields and an output folder, then copy. Share independently offers a whole clip or saved range, defaulting to the range, and produces H.264 MP4 with all audio mixed to stereo AAC.

In review mode, tap Space to play/pause or hold for 200 ms to play at 3× until release. Arrows seek ±5 seconds, Shift+arrows ±1 second, I/O set markers, and R then 1–5 rates. Every text field, even when empty, consumes normal typing. Press `?` for the cheatsheet. In remains pending until a valid Out is set; Share continues offering the previous saved range. Source videos are never trimmed or rewritten.

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

Project Export preserves original bytes and extensions. Share retains the video stream for whole H.264 clips; all ranges and non-H.264 sources re-encode, preferring NVIDIA P5/CQ19 with x264 medium/CRF18 fallback. Audio tracks are mixed into one stereo AAC track; silent sources remain silent. Range precision follows source video frames and audio samples. Both operations sanitize output names, reject capture-folder destinations, and never overwrite existing files. Cancellation removes operation-owned incomplete files. Outputs remain unmanaged. Exported XMP preserves clip ID and In/Out milliseconds in a DFSorter namespace; automatic Premiere interpretation is not claimed.

Projects defaults collapsed in normal windows and expanded when maximized; use the upper-right toggle. Right-click a project for all actions including Delete. Empty technical notes are hidden; use **Clip → Edit technical condition…**. Icons are vendored under `resources/icons` with their upstream license; Node is not required at runtime.

## Verification

```powershell
uv run pytest -q -p no:faulthandler
uv run ruff check src tests
uv run ruff format --check src tests
```

GUI tests open temporary windows and use disposable catalogues, never the working catalogue. They generate H.264/AV1 media, check decoded frames/audio/seek behavior, and capture normal/maximized windows. Windows can emit a handled COM exception through Python's faulthandler while creating a Qt window; the command above avoids that misleading diagnostic.

Home and Config are intentionally lightweight. Automatic folder polling, an installer, a graphical schema editor, general video editing, and Premiere-specific XMP interpretation are outside this delivery. Source inspection, copying, and sharing run in a background worker. Share cancellation terminates the active subprocess; scanning cancellation waits for the current ffprobe call (up to 20 seconds). Library search currently evaluates catalogue rows in memory.

Playback uses Qt native video rendering with hardware decoding where supported and software fallback. D3D11 decoding of H.264 and AV1 was confirmed on this machine with Qt diagnostics. To inspect decoder selection, set `QT_LOGGING_RULES=qt.multimedia.ffmpeg.hwaccel=true;qt.multimedia.playbackengine.codec=true` before launching. Native video surfaces may be absent from QWidget screenshots; decoded-frame artifacts are captured separately by tests. Subjective smoothness and audio balance still need acceptance with real captures.
