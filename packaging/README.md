# Portable release dependencies

`build-release.ps1` pins FFmpeg by archive name, release URL and SHA-256.
Use a month-end BtbN build when updating this pin: upstream retains the last
build of each month for two years, but other daily builds expire after 14 builds.
Check the asset and checksum before updating all three values, and update
`THIRD-PARTY-NOTICES.txt` to reference the same release.

Upstream retention policy: https://github.com/BtbN/FFmpeg-Builds#release-retention-policy

Release CI builds the portable ZIP and creates a draft release when a version
tag is pushed. Do not generate the portable ZIP on the development device.
