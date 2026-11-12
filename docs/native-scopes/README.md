# Experimental native video scopes (macOS)

An opt-in libmpv provider for waveform, RGBY parade and vectorscope analysis of
the presented frame, plus the default-off decoder raster used for pixel-exact
paused capture. Both are built only with `enable-native-scopes`; released
package URLs and the normal patch sequence are unchanged.

## Design

`aagedal-scopes` analyses the encoded source signal (HDR transfer values are
kept, never tone mapped) and returns premultiplied BGRA plots.

- **GPU (gpu-next).** The command asks the VO for scopes
  (`VOCTRL_AAGEDAL_SCOPES`). `vo_gpu_next` takes the frame a screenshot would
  capture, renders it once with libplacebo into an RGBA16 raster in its own
  color space (decode, crop, rotate and box-average only), then compute passes
  bin every sample with atomics, find the plot maxima and paint the plots. Only
  the painted plots are read back. VideoToolbox frames are never downloaded.
  Dolby Vision is analysed after reshaping, as the BT.2020 PQ signal it
  decodes to.
- **CPU fallback.** For any other VO (vo=null, the libmpv render API) the VO
  frame is analysed with the core unlocked. Hardware frames are mapped
  read-only instead of downloaded where FFmpeg supports it (VideoToolbox),
  swscale area-averages to the analysis size, and the binning uses 12-bit
  lookup tables instead of per-sample transfer functions.

Both backends share one definition of the bins and paint rules (`video/scope.c`;
the GLSL in `video/out/gpu_next/scopes.c` mirrors it). Plot columns follow the
displayed image: rotation moves samples between columns, vertical flips (applied
after rotation in display space) do not.

Supported signals: any SDR transfer with known primaries, and PQ or HLG. Luma
and chroma coefficients come from the source primaries. PQ uses ST 2084 on a
10,000-nit logarithmic axis; HLG uses the nominal 1,000-nit display with a fixed
1.2 system gamma. ICC-tagged sources and other HDR transfers are rejected so
the consumer can fall back to display-space scopes.

## API

`aagedal-scopes <width> [<plots>] [<backend>] [<analysis>]`

- `width`: 64–1440; plots are `w × h` with `h = round(w × 9/16)`, the
  vectorscope `h × h`.
- `plots`: `waveform`, `parade`, `vectorscope` joined with `+` (default: all).
  Only requested plots are computed and returned.
- `backend`: `auto` (default: GPU, else CPU), `gpu` or `cpu`.
- `analysis`: longest edge of the analysis raster, 0 for the default (1920 on
  the GPU, the plot width on the CPU). Never upscales.

Protocol 2 result: `protocol`, `w`, `h`, `track-id`, `pts`, `primaries` and
`transfer` (mpv's names, as in `video-params`, e.g. `bt.2020`/`pq`),
`peak-nits`, `dolby-vision`, `backend` (`gpu`/`cpu`), `analysis-w`,
`analysis-h`, `format="bgra-premultiplied"`, and a byte array per requested
plot (`waveform`, `parade`, `vectorscope`). The command fails during pending
seek/restart, stop or track replacement, and for unsupported signals.

Changes from protocol 1: plots and backend are selectable, color names follow
mpv, `hardware-transfer` is gone (GPU frames are never transferred; CPU frames
are mapped), and `backend`, `analysis-w/h` and `dolby-vision` are new. The
consumer must check `protocol`, all node types and exact payload lengths.

`aagedal-decoder-raster` (protocol 2, unchanged) still requires
`--aagedal-decoder-raster=yes` and returns the paused decoder raster, with the
properties `aagedal-decoder-raster-pts` and `aagedal-decoder-raster-version`.

## Build

```sh
make build enable-gpl platform=macos enable-native-scopes
```

The option requires `enable-gpl` and exactly `platform=macos`, and restricts
source builds to arm64. After the standard MPVKit mpv patches, the build applies
`Sources/BuildScripts/experimental/native-scopes/mpv-0.42.0-native-scopes.patch`
through `scripts/prepare-native-scopes.py`, which recognises an exact previous
application and rejects partial or modified ones. A normal build rejects a
cached experimental mpv tree; use separate checkouts for normal and
experimental work.

The patch no longer carries CoreAudio changes: mpv 0.42.0 fixed the channel-map
handling upstream ("ao_coreaudio: remove misusage of audio unit channel map
API"), and the init-failure cleanup is upstream too.

## Validation and performance

Evidence is in [evidence-20261112](evidence-20261112/), on an Apple M5 Pro,
macOS 27.2, mpv 0.42.0, libplacebo 7.387.0, MoltenVK 1.4.2. The machine was
under unrelated heavy load (load average above 20) during the runs, so timings
are conservative.

- **Signal.** Five lossless RGB16 fixtures (SDR, PQ and HLG greys and color
  bars) match independently computed bins for every occupied waveform, parade
  and vectorscope pixel, within one bin, on both backends.
- **GPU/CPU agreement** on UHD SDR/PQ/HLG video at the same 720-pixel analysis
  raster: 76–85 % of waveform and 73–95 % of parade intensity is within one bin
  of the other backend, 50–58 % for the vectorscope. The backends upsample
  chroma differently (libplacebo as displayed, swscale for the fallback).
- **Math.** 242 accumulation/paint cases (sizes, transfers, rotations, plot
  masks, extreme values) pass under ASan/UBSan.
- **Lifecycle.** Rejection before load, invalid width, single-plot and default
  plot sets, PTS advancing during playback, accurate seek and stop.
- **Decoder raster.** Software and actual VideoToolbox decoding give
  byte-identical rasters for 8-bit SDR (NV12) and 10-bit PQ (P010). Rotations
  of 90/180/270° and horizontal/vertical flips match the mapping exactly and are
  byte-identical to FFmpeg's own auto-rotated decode.

- **Recipe.** A fresh checkout builds with `enable-native-scopes` and the
  resulting libmpv contains the new commands. This needed a fix in
  `base.swift`: framework creation ignored the arm64-only restriction and
  skipped every source-built xcframework.

Timings at plot width 720 on UHD 60 fps SDR/PQ/HLG (all three plots, mean of 30
calls, [uhd-timing.json](evidence-20261112/uhd-timing.json)):

| | GPU (1920 px analysis) | CPU (720 px analysis) | `screenshot-raw` alone |
|---|---|---|---|
| Paused, wall time | 1.9–3.3 ms | 6.2–11.9 ms | 14–21 ms |
| Paused, process CPU time | 1.6–1.9 ms | 6.0–11.6 ms | |
| Playing, wall time | 7.0–9.3 ms | 6.8–13.1 ms | 15–26 ms |

The GPU backend analyses about seven times as many samples for a fraction of the
CPU time. During playback its latency is dominated by waiting for the VO thread
to finish presenting the current frame, not by the analysis. The earlier 0.41
CPU-only candidate measured 4.9–11.7 ms paused at 720 px.

Decoder raster capture of an UHD frame: 1.7–2.1 ms for 8-bit SDR, 15–16 ms for
10-bit PQ (RGBA64 conversion), 2.5–7.1 ms with rotation or flips
([decoder-raster.json](evidence-20261112/decoder-raster.json)).

## Repeat checks

Using a disposable upstream mpv v0.42.0 checkout with all
`Sources/BuildScripts/patch/libmpv/*.patch` files applied in sorted order:

```sh
python3 scripts/test-native-scopes.py /path/to/mpv \
  --placebo-include dist/libplacebo/macos/thin/arm64/include
```

This tests patch application, idempotence, modified-source rejection and the
sanitized math cases. `Tests/NativeScopes/mpv_scopes_harness.c` and
`mpv_raster_harness.c` are native clients; compile them as Objective-C with
`-DSCOPE_GPU` for gpu-next on a CAMetalLayer (needed for the GPU backend and for
actual VideoToolbox frames), or as C for vo=null. Link them like the `mpv`
executable of the candidate build. Then:

```sh
python3 scripts/validate-native-scopes.py /path/to/scopes-client /tmp/scope-results \
  --ffmpeg /path/to/ffmpeg --compare uhd-sdr.mkv --compare uhd-pq.mkv
```

The scopes client takes `INPUT OUTPUT_PREFIX HWDEC WIDTH [play]`
(`SCOPE_ANALYSIS` overrides the analysis edge); the raster client takes
`INPUT OUTPUT HWDEC` and fails if requested hardware decoding falls back to
software.

The [evidence-20261015](evidence-20261015/) directory documents the earlier mpv
0.41.0 CPU-only candidate (protocol 1) and is kept for reference.
