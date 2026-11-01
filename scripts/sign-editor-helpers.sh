#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Sign (Developer ID, hardened runtime, secure timestamp) and notarize the editor helpers
# staged by prepare-editor-release.py, then write the release ZIP and SHA256SUMS.txt.
# Usage: scripts/sign-editor-helpers.sh <prepared-release-directory>
# Environment: MPVKIT_SIGN_IDENTITY (default "Developer ID Application"), MPVKIT_NOTARY_PROFILE
# (default "notary", a `xcrun notarytool store-credentials` keychain profile).
set -euo pipefail
release="$(cd "${1:?prepared release directory}" && pwd)"
helpers="$release/ffmpeg-helpers"
identity="${MPVKIT_SIGN_IDENTITY:-Developer ID Application}"
profile="${MPVKIT_NOTARY_PROFILE:-notary}"
tag="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["tag"])' "$release/release.json")"
archive="$release/ffmpeg-helpers-${tag#aagedal-1.1.0-}-arm64.zip"
[[ -f "$helpers/ffmpeg" && -f "$helpers/ffprobe" && ! -e "$helpers/notarization.json" ]] || {
  echo "Expected freshly prepared, unsigned helpers in $helpers" >&2; exit 1; }

for name in ffmpeg ffprobe; do
  codesign --force --sign "$identity" --options runtime --timestamp --identifier "com.mpvkit.editor-helpers.$name" "$helpers/$name"
  codesign --verify --strict --verbose=2 "$helpers/$name"
  codesign -dvv "$helpers/$name" 2>&1 | grep -E '^(Authority=Developer ID Application|Timestamp=|CodeDirectory.*runtime)'
done

work="$(mktemp -d "${TMPDIR:-/private/tmp}/mpvkit-notarize.XXXXXX")"
trap 'rm -rf "$work"' EXIT
ditto -c -k --keepParent "$helpers" "$work/submission.zip"
xcrun notarytool submit "$work/submission.zip" --keychain-profile "$profile" --wait --output-format json > "$work/submission.json"
id="$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); print(r["id"]); sys.exit(r["status"] != "Accepted")' "$work/submission.json")" || {
  cat "$work/submission.json" >&2; exit 1; }
xcrun notarytool log "$id" --keychain-profile "$profile" "$helpers/notarization.json"
python3 - "$helpers/notarization.json" <<'PY'
import json, sys
log = json.load(open(sys.argv[1]))
assert log['status'] == 'Accepted' and not log.get('issues'), log.get('issues')
assert {item['path'].rsplit('/', 1)[-1] for item in log['ticketContents']} >= {'ffmpeg', 'ffprobe'}
PY

rm -f "$archive"
ditto -c -k --keepParent "$helpers" "$archive"
(cd "$release" && shasum -a 256 ./*.zip ./*.tar.gz | sed 's#  \./#  #' > SHA256SUMS.txt)
for name in ffmpeg ffprobe; do echo "$name $(shasum -a 256 "$helpers/$name" | cut -d' ' -f1)"; done
echo "archive $(shasum -a 256 "$archive" | cut -d' ' -f1) $archive"
