# Editor build: one FFmpeg for the libraries and the helpers

Aagedal Film Constructor links this fork's macOS GPL FFmpeg into its development playback
runtime and runs `ffmpeg`/`ffprobe` as media helpers for export, proxies, conversion,
stabilisation and noise reduction. Since `aagedal-1.1.0-n9.0.2-editor.2`, both come from
one FFmpeg configure run. The release publishes the `Libav*-GPL` frameworks and the arm64
programs that configure run built, so the app carries one FFmpeg build.

## Configuration

Compared with `editor.1`, the shared configuration adds components and removes none:

- **Every decoder and demuxer.** The helpers convert whatever FFmpeg can read, so the
  playback allow-lists for these two kinds are gone. Parsers and bitstream filters were
  already complete.
- **x264** (GPL, `stable` at `b35605a`), built from source by `BuildX264`, and
  published as `Libx264-GPL`. `_FFmpeg-GPL` depends on it.
- **Encoders:** `prores_ks`, `libx264`, `ffv1`/`qtrle` for verification fixtures, and
  `rawvideo`/`wrapped_avframe`, the defaults of the `rawvideo` and `null` muxers.
- **Filters:** the editor's export, transition, title, audio-effect, stabilisation and
  noise-reduction filters. That is every entry in the editor's
  `Configuration/FFmpegRequirements.json`, including test sources (`sine`, `testsrc2`,
  `smptehdbars`, …) and checks (`psnr`).
- **Muxers:** `wav`, `pcm_f32le`, `pcm_s16le`, `rawvideo`, `null`, `nut` and `image2`.
- **Input device:** `lavfi`, for generated fixtures.

On the build host's architecture (arm64), configure also builds `ffmpeg` and `ffprobe`.
`ffplay` is disabled, so the build no longer needs Homebrew SDL2. `-Wl,-dead_strip_dylibs`
drops the glib/intl/pcre2 dylibs that `smbclient.pc` lists but nothing references, so
the programs link only system libraries. Neither change affects the static archives.

## Building and publishing

```sh
# Isolated rebuild of x264, FFmpeg and libmpv from an existing dependency cache:
python3 scripts/rebuild-macos-audio.py --cache-root /path/to/MPVKit-with-dist \
  --output /new/staging --programs --build
# After committing the recipe: assets, helpers, sources and a Package.swift patch.
python3 scripts/prepare-editor-release.py --candidate /new/staging --tag aagedal-1.1.0-n9.0.2-editor.N \
  --requirements /path/to/Aagedal_Film_Constructor/Configuration/FFmpegRequirements.json --output /new/release
# Developer ID signing, notarization, the helper ZIP and SHA256SUMS.txt:
scripts/sign-editor-helpers.sh /new/release
```

`prepare-editor-release.py` checks the compiled `config_components.h` of both slices
against every entry of the editor's requirements, optional ones included. It also requires
that the helpers link only system libraries and that the arm64 configure line is embedded
in both programs and in `libavcodec.a`. `ffmpeg-helpers/build.json` records that
configuration, the source revisions and the hashes. The editor's
`scripts/ffmpeg-copies-audit.py --require-same-build` compares it with the configuration
reported by the linked runtime.
