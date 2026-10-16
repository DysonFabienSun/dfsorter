# Portable release dependencies

`build-release.ps1` pins FFmpeg by archive name, release URL and SHA-256.
Use a month-end BtbN build when updating this pin: upstream retains the last
build of each month for two years, but other daily builds expire after 14 builds.
Check the asset and checksum before updating all three values, and update
`THIRD-PARTY-NOTICES.txt` to reference the same release.

Upstream retention policy: https://github.com/BtbN/FFmpeg-Builds#release-retention-policy

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
