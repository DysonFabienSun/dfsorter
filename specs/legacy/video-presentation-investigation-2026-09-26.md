# Browse video reveal investigation — 2026-09-26

Archived after the presentation fix. The findings and recommendations below describe
the earlier `1b62cac` revision; the final resolution is recorded at the end.

Investigated revision: `1b62cac` (Reveal prepared video after tab layout settles).
Application source and tests were not changed. Diagnostic scripts, traces, and recordings are under `cache/video-investigation/`.

## Finding

The current change fixes the Qt widget's first-show geometry but leaves a native rendering race. A preloaded video is declared ready while the hidden Windows video windows still have their initial 640 × 480 dimensions. Browse subsequently exposes those windows while the renderer is adapting to 908 × 511. A screen recording captures an incorrectly letterboxed/squashed image for approximately 35 ms before the correct image appears.

Preloading succeeded well before the click. Additional time on Home does not by itself prepare the native surface at its eventual visible dimensions.

## Reproduction and evidence

Used a SQLite backup of the existing catalogue, copied settings and configuration, and the selected existing recording, with dark mode and the application's normal 1400 × 918 window. The diagnostic instance disabled startup and focus scans to isolate presentation. This establishes that scanning is not required to trigger the defect; it does not measure startup with scanning enabled. Source recordings and the original catalogue/settings were not modified.

Windows device pixel ratio was 1.0. The installed backend identified itself as `mpv v0.41.0-1023-g69e63f425`. Recorded Qt geometry, Windows `GetClientRect` for the Qt surface and mpv child HWND, libmpv `osd-dimensions`, and the desktop pixels within the application window. The unobstructed capture temporarily kept the diagnostic window on top. FFmpeg was requested to sample at 120 fps; this is not a claim of exact display presentation timestamps.

Representative baseline (`capture-trace.json`, times relative to diagnostic setup completion):

| Event | Time | Qt video size | Native host / mpv child |
| --- | ---: | --- | --- |
| Preload starts | 182 ms | 640 × 480 | 640 × 480 / not yet created |
| Aspect ratio applied | 520 ms | 640 × 360 | 640 × 480 / 640 × 480 |
| Initial frame readiness signal | 605 ms | 640 × 360 | 640 × 480 / 640 × 480 |
| Readiness after initial seek | 676 ms | 640 × 360 | 640 × 480 / 640 × 480 |
| Preload marked complete | 784 ms | 640 × 360 | 640 × 480 / 640 × 480 |
| Browse clicked | 3031 ms | 640 × 360 | 640 × 480 / 640 × 480 |
| Tab handler returns | 3175 ms | 908 × 511 | 640 × 480 / 640 × 480 |
| Qt Show event | 3213 ms | 908 × 511 | 640 × 480 / 640 × 480 |
| `show()` returns | 3216 ms | 908 × 511 | 908 × 511 / 908 × 511 |

At the click, `awaiting_frame=False`, `needs_cover=False`, and `native_surface_warmed=False`. Preloading had completed roughly 2.25 seconds earlier.

The independent screen recording `browse-entry.mkv` shows:

- At 0.776 s, video is visible with approximately 64 px black bands at both top and bottom (`visible-02.png`).
- At 0.785 s, that distorted video remains visible (`visible-03.png`).
- At 0.811 s, video fills the intended surface correctly (`visible-04.png`).

The visible incorrect state lasts about 35 ms in this recording. This reproduces a symptom consistent with the previously reported 33 ms; it does not establish an invariant duration or exactly one source/display frame.

Before reveal, mpv reports a 640 × 480 output with 60 px top and bottom margins. Stretching that old output to 908 × 511 produces margins of `60 / 480 × 511 ≈ 64 px`, matching the capture. This strongly supports stale output being exposed during resize. The precise GPU swap-chain/compositor operation was not instrumented, so that internal mechanism remains an inference. Source resolution is not changing.

## Pipeline in the repository

1. **Page target and preload.** `Window` starts on Home. `schedule_preload()` restarts a 150 ms single-shot timer. `prepare_inactive_clips()` selects the expected Browse clip and Editing session clip, then loads each inactive player. The cache key covers clip/source identity, file size/mtime, saved range, and start-position settings. Library refreshes can restart this debounce or change its target. See `ui.py:667`, `ui.py:1855`, `ui.py:1885` and `ui.py:1900`.
2. **Separate player instances.** Browse, Editing and Export use the shared `Player`, with separate `MpvBackend` instances. Browse and Editing are preloaded; Export is not included in `prepare_inactive_clips()`.
3. **Native embedding.** `VideoSurface` requests a native Qt window. `MpvBackend._initialize()` gives its HWND to libmpv via `wid`, using `vo=gpu`, D3D11 on Windows and `hwdec=auto-safe`. On Windows mpv creates its own child window inside that HWND. The video is not painted by Qt's ordinary widget painter. See `playback.py:36`, `mpv_backend.py:114`, and the [mpv embedding documentation](https://mpv.io/manual/stable/#options-wid).
4. **Load and initial seek.** `Player.load()` resets playback and starts the 15-second timeout. Loading is paused. `file-loaded` marks backend media preparation and configures audio mixing. `playback-restart` becomes the application's `frameReady` signal. The first signal requests the saved In point, or the near-end fallback; the next signal allows preview readiness. Generation checks reject stale media events. See `mpv_backend.py:163`, `playback.py:545` and `playback.py:580`.
5. **Geometry.** `video-out-params` supplies the video's display aspect ratio. `AspectVideoContainer` fits and centers the video QWidget within available space. That property describes video dimensions; it is not an acknowledgement that the Windows output window or displayed frame has caught up. See `playback.py:51` and `mpv_backend.py:223`.
6. **Current readiness timer.** `finish_preview_if_ready()` emits `preview_render_ready`, then starts a first-use delay of at least 100 ms, or two refresh intervals when already warmed. `complete_preview()` clears `awaiting_frame` and only marks the native surface warmed if it is visible. When preloading on Home, the window's `player_render_ready()` handler does nothing because this is not an active covered player. The delay therefore expires while the surface remains hidden. See `playback.py:598`, `ui.py:1190`.
7. **Browse entry.** `page_needs_cover()` accepts a matching preload key and `awaiting_frame=False`; it does not require native warm-up. `Browse.load(prepared=True)` reuses the loaded media. The latest change hides the video, changes the page/layout, then queues `show_ready_video()` with a zero-delay timer. That callback activates Qt layout, sizes the video widget and calls `show()`. It does not mask the native surface or wait after its native resize. See `ui.py:1274`, `ui.py:1292`, `ui.py:1468`, `browse.py:190`.
8. **Renderer and display.** Native resizing, GPU rendering and desktop presentation can outlive the Qt Show event and `show()` return. The observed output-size update is useful diagnostic evidence, but does not alone prove the newly rendered pixels are already on screen.

Qt documents that geometry events for hidden widgets can be deferred until show: [QWidget geometry](https://doc.qt.io/qt-6/qwidget.html#geometry-prop). In this run, the native rectangles themselves remained stale until show.

## Why the recent fixes miss this case

- `af39306` preloads media but does not prepare the hidden native output for the later page geometry.
- `bd04938` lets prepared tab entries bypass the transition cover.
- `1b62cac` delays reveal until Qt layout has settled. That addresses one stage, but calls `show()` with no native masking/warm-up in this path.
- `test_prepared_video_first_show_uses_final_size` records `QWidget.size()` at Show and compares it with the size 50 ms later. Both are 908 × 511 in the failing scenario. It checks neither HWND dimensions nor displayed pixels.

Ran exactly that existing regression: **1 passed in 2.73 s**, while separately reproducing the visible defect on the same revision. The test asserts a useful layout property, but cannot validate the claimed visual fix.

There is also a mismatch with `specs/ui-layout-guide.md:323`, which explicitly requires clipped native warm-up and at least 100 ms for the first native show. Inactive preload currently consumes the timer without doing the native show. Prepared entry then bypasses that step. `native_surface_warmed` remains false even after this prepared fast path because that path never updates it.

## Controlled comparisons

The experiments patched only methods in the temporary diagnostic process; production files were unchanged.

- **Additional hidden delay:** requested another 250 ms before the same reveal (roughly 239 ms elapsed in that timer run). Native host and mpv child both remained 640 × 480 until `show()`, although Qt had long reported 908 × 511. Merely increasing the pre-show wait does not address this mechanism. See `delayed-trace.json`.
- **Masked native show:** applied the existing 1 × 1 region mask, ran the same reveal, and cleared the mask after a 100 ms timer. Both native rectangles and mpv output dimensions updated while clipped. The capture's first visible video was correctly sized. See `masked-trace.json`, `masked-entry.mkv`, and `masked-03.png`.

The second experiment supports the existing specification's approach. One captured success with a fixed timer is not proof of a production-ready, universally reliable synchronization scheme.

## Recommended correction and verification

Separate **media prepared** from **surface ready to reveal**. Reuse preloaded media, settle the target page geometry, show its native surface with a clipped visible region, let rendering catch up at that geometry, and only then expose it. Apply this through a shared presentation path for prepared and newly loaded videos rather than another Browse-only timer.

Start the specified first-show warm-up after the actual clipped native show. Scope readiness to both media generation and presentation geometry; prior visibility alone is insufficient after a size or DPI change. Guard callbacks against tab changes, replacement media and superseded presentation attempts. Errors, unavailable media and timeouts must still reveal the appropriate status and release masking.

Observe mpv output dimensions if needed to avoid beginning the final warm-up before resize is acknowledged, but do not treat a dimension notification as proof of GPU presentation. Keep the existing backend and masked warm-up as the focused correction; a renderer integration rewrite is not justified by this investigation.

The acceptance check must include the first displayed frames of dark-mode Home → Browse after completed preload, with native geometry tracing as supporting evidence. Also target entry before preload completes, a return after geometry changes, and stale callbacks from rapid tab changes. DPI changes and window resizing are distinct checks. Preserve paused position and preload reuse. Avoid replacing the small-frame flash with an unnecessary whole-page blank flash.

The initial screen capture was obstructed and excluded; its extracted images were removed. The retained baseline and masked evidence images referenced here show the diagnostic application unobstructed. Timing instrumentation and recording can affect scheduling; the conclusion is based on the repeated ordering and captured pixels, not a fixed millisecond guarantee.

## Implemented resolution

Prepared tab entry now displays a still from the paused decoded frame before the page
can paint. The native surface then shows under a mask after the splitter settles. Its
first warm-up waits at least 100 ms; later shows at the same size wait two display
refresh intervals. A size or display-scale change restarts warm-up. Only a current
tab, media generation, and reveal attempt may remove the mask. Empty or failed media
skip this warm-up.

Targeted tests cover prepared Browse and Editing entry, first-show geometry, tab and
clip cancellation, resize, empty Browse, and the existing covered loading path.
Dark-mode capture `cache/video-investigation/fixed3-entry.mkv` shows the first
displayed Browse frame at the intended size, without the earlier letterboxed frame
or an intermediate blank video area. The capture is diagnostic evidence for the
tested Windows configuration, not a guarantee across every display and decoder.
