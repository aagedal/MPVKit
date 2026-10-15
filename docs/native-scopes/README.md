# Experimental native video scopes (macOS arm64)

This branch adds an opt-in libmpv provider for waveform, RGBY parade and
vectorscope analysis. It reads the current VO input frame, preserves source HDR
transfer values, downsamples once, and returns all three diagnostic images with
the frame PTS and track/color metadata. It does not invoke `screenshot-raw` or
open a second decoder. Native CPU analysis releases mpv's core lock while doing
the expensive work; the app admits one request at a time.

`Package.swift` remains on the existing released binary URLs and checksums.
Selecting this branch as a Swift package therefore does not activate the new
provider. Build and publish a separately qualified candidate before repinning
an app. No existing release is replaced, and the decoder-raster cache remains
explicitly default-off.

The audio-meter build moves the published CoreAudio cleanup fixes into the
shared patch sequence. This experimental patch is rebased onto that sequence
and retains the cleanup and hotplug ordering. The historical numerical evidence
below predates that source-maintenance change; it does not qualify a newly built
scope binary. See [audio analysis](../audio-meter/README.md).

## Existing app compatibility

Aagedal Media Converter currently requires MPVKit revision
`400202b687841fb394cbf0ef59ad8c6fcfc1275b` in both its project and resolved file.
Moving MPVKit `main` does not change that exact dependency. This change also
leaves `Package.swift` byte-identical to that revision, with identical Swift
wrapper trees and all existing binary URLs/checksums. Consumers choosing the
new revision still receive the same released binaries. The new source provider
requires the explicit experimental build option; it is not enabled in normal
builds. No release assets or Converter files were modified.

See [converter-compatibility.json](evidence-20261015/converter-compatibility.json).
This is a dependency identity check, not a claim that Converter was rebuilt
against newly published scope binaries. Publishing and repinning such binaries
requires separate compatibility qualification.

## Build

With the repository's normal build prerequisites installed, use a fresh checkout:

```sh
make build enable-gpl platform=macos enable-native-scopes
```

The experimental option requires both `enable-gpl` and exactly `platform=macos`.
It restricts source builds to arm64, including FFmpeg and libmpv. Qualified
prebuilt auxiliary libraries may retain their existing slices. Other platforms
and x86_64 are not qualified for this candidate. Default builds do not apply
the experimental patch. A normal build rejects a cached experimental mpv tree;
use separate checkouts/build directories for normal and experimental work.

After the standard MPVKit mpv patches, the build applies
`Sources/BuildScripts/experimental/native-scopes/mpv-0.41.0-native-scopes.patch`.
The patch includes:

- The native waveform/parade/vectorscope command and bounded C computation.
- The protocol-2 paused decoder-raster prerequisite shared with the validated
  application candidate. Its cache stays off unless `aagedal-decoder-raster=yes`
  is explicitly supplied. Live scopes do not need that cache.
- The retained CoreAudio routing/cleanup source corrections used by that
  candidate, so this source build preserves those already-published fixes.

The combined patch applies cleanly to upstream mpv v0.41.0 after the current
MPVKit patch sequence. The resulting source files were compared with the
previously built and accepted candidate, including the CoreAudio files.
The opt-in helper is idempotent for an exact application and rejects partially
applied or subsequently modified provider sources before changing them.

## API

`aagedal-scopes <width>` accepts 64–1440. Protocol 1 returns:

- `protocol`, `w`, `h`, `track-id`, `pts`, `primaries`, `transfer`, `peak-nits`,
  `format="bgra-premultiplied"`, and `hardware-transfer`.
- `waveform` and `parade`: tightly packed `w × h × 4` byte arrays.
- `vectorscope`: tightly packed `h × h × 4` byte array.

`h = round(w × 9/16)`. Images contain premultiplied BGRA8 diagnostic colors,
intended for sRGB display. They are not source-pixel proof. Consumers must check
all node types, exact payload lengths, metadata combinations, finite timestamps
and active track identity before copying. Use `mpv_free_node_contents` normally.

Input is the post-filter, pre-display-rendering video frame. The provider applies
crop and orthogonal rotation/reflection to its analysis. It fails during pending
seek/restart, stop/replacement, or unsupported representations. Dimensions are
bounded before hardware download to 8192 per axis and 33,554,432 pixels. Analysis
is sampled to the configured width; tiny excursions between samples can be
missed. VideoToolbox download still occurs. GPU histogram computation is not
implemented.

Supported signals are BT.709 SDR and BT.2020 PQ/HLG. PQ uses ST 2084 and a
10,000-nit logarithmic axis. HLG retains the app's fixed 1.2 system gamma and
1,000-nit peak assumption. Luma/chroma coefficients and UI targets must match
primaries. The example consumer uses BT.2020 vectorscope targets for native HDR.
ICC/Dolby Vision and other unsupported combinations fall back at the consumer.

The application preserves its screenshot path for A/B display-space difference
scopes, and AVPlayer outputs for ProRes RAW. These are separate consumer paths;
a native source-signal scope should not silently replace display-space metrics.

## Validation and performance

The source-identical arm64 candidate was built in the Aagedal Media Player
workspace before porting its patch into this branch. Receipts and numerical
results are retained in [evidence-20261015](evidence-20261015/). On macOS 27.0.1:

- 38 hosted scope/consumer tests pass without skips, covering typed/oversized
  payload rejection, native SDR/PQ/HLG, all three plots, display-capture fallback
  and return, and in-flight completion handling on stop.
- The existing native-raster hosted test passes all 20 retained fixtures against
  the new libmpv binary, including actual VideoToolbox decoding and seek/reuse/
  resume revocation. The existing default-off provider gate stays intact.
- Five independent lossless RGB16 signal fixtures verify every occupied waveform,
  parade and vector bin, with one-bin tolerance for conversion/float boundaries.
- Six UHD 60 fps runs cover SDR/PQ/HLG with software and actual VideoToolbox decode.
  The three first-frame plots are byte-identical between hardware/software in
  all three workloads. Playback PTS, accurate seek, unload and invalid-width
  rejection pass.
- 120 transfer/orientation/resolution math cases pass under ASan/UBSan. Sanitizer
  coverage here is the new C math, not the entire mpv/FFmpeg/Metal lifecycle.

At width 720, native all-three-plot analysis averages **4.90–11.70 ms** in the six
UHD runs; screenshot capture alone averages **29.32–33.51 ms**, before the app's
scope computation. Calls are interleaved native first, screenshot second.
The hosted UHD HLG app comparison at a 30 fps scope setting improves from
**19.98 to 29.33 scope updates/s**, with fresh PTS for every captured update.
These rates do not certify 60 fps display presentation or frame lock.

For this branch specifically, the Swift build recipe compiles, invalid option
combinations reject before dependency work, the combined patch applies through
the current normal MPVKit patch sequence, and patch/idempotence/rejection plus
sanitized math checks pass. The full dependency build was not repeated after
adding the opt-in recipe wrapper; the provider's C source is unchanged from the
accepted build. Long-duration/multi-viewer memory and thermal behavior, 8K
performance, physical HDR calibration and general interlaced/filter workloads
remain unqualified.

## Repeat source checks

Using a disposable upstream mpv v0.41.0 checkout, apply all existing
`Sources/BuildScripts/patch/libmpv/*.patch` files in sorted order, then run:

```sh
python3 scripts/test-native-scopes.py /path/to/mpv
```

Only a temporary copy is modified. This tests full patch application,
idempotence, modified-source rejection, and the 120 sanitized math cases.
`Tests/NativeScopes/mpv_scopes_harness.c` is the native client used for signal,
lifecycle and timing runs. Compile as Objective-C with `-DSCOPE_GPU` for an
interactive Metal surface; ordinary C uses the null VO/software path. Link it
with this candidate's libmpv and the same FFmpeg/auxiliary libraries as the build.

```sh
python3 scripts/validate-native-scopes.py /path/to/client /tmp/new-scope-results \
  --ffmpeg /path/to/ffmpeg
```

The signal validator generates independent lossless RGB16 fixtures. The GPU
client takes `INPUT OUTPUT_PREFIX HWDEC WIDTH [play]`; hardware validation must
report an actual hardware transfer, not software fallback. Retain new source,
binary checksums, fixtures and evidence for any future provider changes.
