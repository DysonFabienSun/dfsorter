# Portable release dependencies

## Retained native dependencies

`dependencies.json` is the single pin manifest for Windows x64 libmpv and FFmpeg.
It records each archive URL, version, SHA-256, required binary/licence hashes and
upstream provenance. `dependencies.ps1` downloads only from the dedicated
DFSorter dependency release, verifies before caching, and checks extracted files
before use. Cache hits require no download. Corrupt archives fail with an explicit
error; incomplete or damaged extraction caches are restored from the verified ZIP.
Failed downloads do not leave an archive that later builds could mistake for valid.

Large archives are GitHub release assets, not Git blobs or Git LFS objects. The
retained release uses a non-application tag (`dependencies-windows-x64-2026-11-06`),
is marked prerelease, and is explicitly excluded from latest-release selection.
It does not trigger the `v[0-9]*` application build workflow and is never returned
by the application's stable `/releases/latest` update check. Do not delete, replace
or overwrite its assets: older source tags depend on those exact bytes.

`setup-playback.ps1` installs the verified DLL and licences from the retained
libmpv ZIP. The build invokes the same setup and obtains FFmpeg through the same
helper; no upstream daily archive, raw licence fetch, prior application release or
7-Zip download is needed. The libmpv bundle preserves the existing DLL identified
by mpv commit `69e63f425a`; its original upstream daily archive expired, so the
bundle records that recovery provenance. The FFmpeg asset is the unchanged BtbN
month-end archive. No native runtime versions are upgraded by this storage change.

Fresh setup/builds still download these assets from GitHub. Python, Python wheels,
uv and the CI runner/actions keep their existing sources; this is not a fully
offline build environment. Released application ZIPs remain self-contained.

### Updating a dependency

1. Acquire the intended build and its licences; verify upstream checksums and
   provenance. Retain the original archive when available. Document any repackaging.
2. Prepare a new dated dependency release with a non-`v` tag. Use
   `gh release create <dependency-tag> <archives> <manifest> --prerelease --latest=false`
   and a UTF-8 notes file describing versions, provenance and checksums. Do not
   overwrite the older release or use an application version tag.
3. Update `dependencies.json` with the new asset URLs, archive SHA-256 and required
   file hashes. Preserve licence files and update `THIRD-PARTY-NOTICES.txt`.
4. Verify downloads from the retained release and cache reuse with the shared helper,
   run focused dependency checks, then commit the manifest/setup changes. App release
   CI consumes the manifest belonging to the selected application source tag.

Release CI builds the portable ZIP and creates a draft release when a version
tag is pushed. Do not generate the portable ZIP on the development device.

## Draft release changelog

Version tags must be annotated. The `push-version-tag` skill prepares the proposed
changelog from the complete changes since the preceding release and uses that exact
Markdown as the tag annotation. The release-preparation commit still changes only
`pyproject.toml` and `uv.lock`.
Create the tag with `git tag --annotate vX.Y.Z --cleanup=verbatim --file <notes-file>`;
verbatim cleanup preserves Markdown headings that Git otherwise treats as comments.

```markdown
## DFSorter vX.Y.Z Changelog

### Improvements
- Describe a change and its practical effect.

### UI fixes
- Describe a visual or interaction correction.

Full Changelog: https://github.com/DysonFabienSun/dfsorter/compare/vPREVIOUS...vX.Y.Z
```

Use real version numbers and only relevant categories. Before pushing, validate
and extract the annotation with `packaging/read-release-notes.ps1 -Tag vX.Y.Z -OutputPath <temporary-notes-file>`.
CI performs the same validation before building, then passes the extracted Markdown
to `gh release create --notes-file`. Lightweight tags, mismatched headings and missing
comparison links fail instead of falling back to generated notes. CI attaches the
portable ZIP and leaves the release as a draft; publication remains a separate action.
After pushing, the skill checks CI and the draft's notes and asset before reporting completion.

The workflow re-fetches the original tag object after checkout, because checkout can
replace the runner's local annotated tag with its underlying commit. It verifies
that the restored tag still points to the checked-out source. To retry an existing
tag with a corrected workflow, run the workflow manually from `main` with the `tag`
input, for example `gh workflow run release-windows.yml --ref main -f tag=v1.1.9`.
The selected tag supplies the source and notes; an existing release still aborts the
run, and retrying never requires replacing the remote tag.
