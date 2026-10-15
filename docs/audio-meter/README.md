# Opt-in audio analysis (macOS GPL)

The audio-meter build enables three existing FFmpeg filters in the macOS GPL
libraries: `astats` (per-channel sample peak/RMS), `asetnsamples` (fixed analysis
windows), and `ebur128` (loudness and optional oversampled true-peak metadata).
They do no work until the application explicitly inserts a filter. Normal
playback does not acquire an analysis filter or require capture permissions.
The LGPL products and other platforms retain their existing release artifacts.

The normal mpv source patch sequence also includes the already-published
CoreAudio failure-cleanup and disposed-handle fixes. The experimental scope
patch now applies after those shared patches and retains their cleanup and
hotplug ordering; native scopes and decoder-raster remain opt-in and are not
included in the audio-meter binary release. FFmpeg's existing Metal buffer
compatibility source preparation is now idempotent across repeated builds.

## Consumer example

Using the libmpv command API, insert a uniquely labelled audio filter:

```text
af add @meter:lavfi=[asetnsamples=n=480:p=0,astats=metadata=1:reset=1:measure_perchannel=Peak_level+RMS_level:measure_overall=Peak_level+RMS_level]
```

At 48 kHz this uses 10 ms analysis frames; choose sample counts appropriate to
the actual filter input rate. Query `af-metadata/meter` as `MPV_FORMAT_NODE`.
It is a string-valued map, with keys including `lavfi.astats.1.Peak_level`,
`lavfi.astats.1.RMS_level`, and `lavfi.astats.Overall.Peak_level`. Channel
numbers are one-based. Values are dBFS; silence is `-inf`, not a parse error.
Use `mpv_free_node_contents` for owned results from synchronous property reads;
event-owned asynchronous reply payloads must instead be copied before the next
`mpv_wait_event` and must not be freed by the application.

To enable loudness analysis instead:

```text
af add @loudness:lavfi=[ebur128=metadata=1:peak=true]
```

Read `af-metadata/loudness` for `lavfi.r128.M`, `.S`, `.I`, `.LRA` and
`.true_peak`. **The true-peak metadata is linear amplitude**, unlike the dBFS
sample peaks from `astats`; convert positive amplitudes with `20*log10(value)`.
Loudness values use LUFS/LU as appropriate. Warm-up, seeks and track replacement
require application handling; a live filter is not a programme compliance test.
True-peak oversampling has additional CPU cost and is independently opt-in.

Remove only the application's own labelled filter when closing the panel:

```text
af remove @meter
af remove @loudness
```

Use bounded asynchronous polling (for example 30 Hz, one query outstanding),
copy/validate metadata types and finite numeric values, and reject old replies
on pause, seek, stop, track or source replacement. Metadata describes decoded
filter input and can lead audible playback because of audio buffering. A query
returns the latest analysis frame, not every intermediate frame: polling alone
can miss short peaks. Windowing/peak hold and audible-clock alignment belong in
the consumer. Only the active decoded track is measured; this does not replace
Converter's simultaneous source meters for inactive mono tracks.

## Build and validation

The ordinary recipe includes these filters:

```sh
make build enable-gpl platform=macos
```

For an isolated library-only rebuild using previously built auxiliary inputs:

```sh
python3 scripts/rebuild-macos-audio.py --cache-root /path/to/cached/MPVKit \
  --output /tmp/mpvkit-audio-candidate --build
```

This exports exact FFmpeg n8.1.2/mpv v0.41.0 source tags, reapplies the source
patches and builds fresh arm64/x86_64 outputs without modifying the cache.
Only standalone FFmpeg/mpv programs are omitted. Keep the resulting build log,
source exports and configurations with the release provenance.

Create a framework-products directory containing the candidate's libmpv and
all seven FFmpeg frameworks, existing auxiliary frameworks and `libMoltenVK.a`.
Then run both architectures (x86_64 requires an Intel Mac or Rosetta):

```sh
python3 scripts/build-audio-meter-probe.py --products /path/to/products \
  --arch arm64 --output /tmp/audio-probe-arm64
python3 scripts/validate-audio-meter.py /tmp/audio-probe-arm64 /tmp/audio-results-arm64
python3 scripts/build-audio-meter-probe.py --products /path/to/products \
  --arch x86_64 --output /tmp/audio-probe-x86_64
python3 scripts/validate-audio-meter.py /tmp/audio-probe-x86_64 /tmp/audio-results-x86_64
```

The acceptance probe checks actual filter registration, runtime insertion,
metadata maps, independent channel peaks/RMS, mono/stereo/5.1/silence, loudness
and true-peak metadata, filter removal, and subsequent exact seek/restart.
Fixtures are generated mathematically, without an external FFmpeg executable.
Physical devices, audible latency and application meter presentation require
consumer validation in addition to this dependency acceptance.

References: [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html),
[mpv af-metadata](https://mpv.io/manual/stable/#command-interface-af-metadata/%3Cfilter-label%3E).

## 2026-10-15 qualification

The release tag is `aagedal-1.0.0-n8.1.2-audio.1`. All eight GPL targets use
fresh macOS arm64/x86_64 archives; upstream versions remain mpv v0.41.0 and
FFmpeg n8.1.2. Existing release assets are not replaced. This release does not
repin either consuming application or implement its meter presentation.

[Retained evidence](evidence-20261015/) records eight signal/filter cases on
native arm64 and the same eight on x86_64 under Rosetta. Known 1 kHz amplitudes
verify sample peak, RMS, loudness calibration and true-peak metadata; each run
also removes its filter and completes an exact seek/restart. The normal and
notification CoreAudio probes each complete four playback/teardown cycles;
initialization and format failure probes each complete four injected failures.
All modes report zero invalid calls and zero remaining listeners. Framework
archive contents/checksums, both architecture slices, GPL configuration and
object deployment floors (at most macOS 12) are checked before preparation.

The isolated FFmpeg build completed before an omitted template stopped package
manifest generation; the template was supplied and the libmpv stage completed
successfully without rebuilding FFmpeg. The reusable staging script includes
the template. Its clean-source staging path and the final Swift recipe compile
were separately checked. The source archive includes the exact source inputs,
staged build recipe and compiler configurations used for this candidate.

Physical Intel hardware, physical output-device changes, audible latency,
consumer app signing, compressed-source meter behavior and long-duration thermal
performance are not established by these dependency tests.
