# DFSorter

DFSorter is a portable Windows app for reviewing gameplay recordings. It catalogues clips, helps organize them into projects, and can share selected ranges or copy project clips for export. Original recordings stay in their existing folders.

Functionalities:

- Live tracking of common recording folders (NVIDIA Shadowplay, Medal, OBS, etc.).
- Interactive gallery of all tracked clips with hardware-accelerated video engine support.
- Robust, editor-friendly clip triage system with ground-up-customizable tags and remarks.
- Clip export options that automatically merge mic tracks and support custom trim settings.
- Portable software where all databases stay local on the machine, in the folder.

## Install

1. Download `DFSorter-Windows-x64.zip` from [Releases](https://github.com/DysonFabienSun/dfsorter/releases).
2. In **Extract All**, choose a writable destination such as `C:\Users\<name>`. The ZIP creates a `DFSorter` folder there. Keep that folder together; do not move `DFSorter.exe` out of it.
3. Double-click `DFSorter.exe`, then add capture folders in the app.

No Git, Python, `uv`, FFmpeg, or 7-Zip installation is required. An unsigned release may show a Windows SmartScreen prompt on first launch.

## Update

Choose **Settings → Check for updates…** in DFSorter. If a newer release is available, confirm the update. DFSorter closes, updates its files, and reopens. Update backups are kept in `backups\updates\` inside the extracted folder.

The catalogue, settings, and editable game definitions remain in that folder under `data\` and `configs\games\`. Updates preserve edited definitions; revised defaults appear in `configs\default-updates\`. Capture recordings stay in their original locations. To move or back up DFSorter, close it first and copy the whole extracted folder.

## Quick Start

1. Open DFSorter and, on **Home**, choose **Add folder…**. Select a recorder folder containing game-named subfolders. Review the scan preview and add the folder; clips will appear in the library without being copied.
2. Open **Browse** to play recordings and find clips with search and filters. Select a clip to watch it, or use **Edit clip…** to work on that clip directly.
3. Open **Session** to create a review queue from selected clips, the first N results, or all current results. **Editing** then opens the queue: add a working title or other metadata, and mark clips Keep or Discard as the review progresses.
4. Add kept clips to a **Project**. Use **Share** for an individual clip or marked range, or open **Export** to copy a project's ready clips to an output folder.

The sections below give a little more context for each part of the app. The top navigation switches between pages; the theme toggle and settings menu are at the upper right.

## Using DFSorter

### Home

Home manages capture folders and shows the clip library. Use **Rescan** to check for new recordings. **More…** provides options to pause or resume scanning, relink a moved folder, or remove a folder from the catalogue. Pausing scanning keeps existing clip information but excludes that folder from new Sessions. Removing a folder from the catalogue does not delete its video files.

### Browse

Browse is for watching and finding clips without starting a Session. Search and filter the library, select a clip to play it, and use the player controls to mark a range. **Share** creates a separate MP4 of the whole clip or a chosen range. **Edit clip…** opens the selected clip in Editing without changing an existing Session.

### Session

Session shows an overview of the library and sets up a review queue. Search, filter, and sort the library first, then create a Session from selected pending clips, the first N pending results, or all pending results. A Session keeps that list and its order while review progress is saved, so it can be resumed later.

### Editing

Editing is where clips in a Session are reviewed. Play the selected clip, enter metadata in the command bar, and decide whether to Keep or Discard it. The field checklist previews the command before it is saved. Ratings, tags, descriptions, and In/Out points can add context; the Projects pane can collect clips for a later export. **Edit clip…** from Browse provides the same workspace for a single clip.

### Projects

Projects group clips for export. Open the **Projects** pane to create or select a project and manage its clips. When the project is ready, open **Export**, choose the project and an output folder, and review any clips that need attention before exporting. Project Export copies whole original video files; it does not trim them to In/Out points.

### Configs

The **Config** page manages game definitions used to recognize games, interpret metadata commands, and build working titles. Choose a game to inspect or edit its fields, aliases, and title order. Changes remain drafts until **Save**. New games can also be added here.

## File & Data Storage

DFSorter keeps its catalogue and settings in `data\` inside the extracted app folder. Editable game definitions live in `configs\games\`; disposable caches live in `cache\`. Capture recordings remain in their original folders. Share and Export create new files in the output folders selected for those actions.

For a backup or move, close DFSorter and copy the entire extracted folder. Back up the source recordings separately if needed; they are not included in the DFSorter folder.

## Feedback

Bug reports, feature suggestions, and recommendations are welcome through [GitHub Issues](https://github.com/DysonFabienSun/dfsorter/issues). A short description of what happened or what would be useful is enough to start a conversation. Thank you for helping improve DFSorter.

## License

DFSorter is released under the [MIT License](LICENSE).
