# Backward playback (`--play-direction=backward`)

mpv plays backward by decoding each keyframe range (batch) forward into a
reversal queue, bounded by `--video-reversal-buffer`, and emitting it in
reverse. Two standard MPVKit patches change how that queue behaves.

## 0007: hardware frames count against the reversal buffer

`mp_image_approx_byte_size()` only summed a frame's AVBufferRefs. For hardware
frames such as VideoToolbox, that is a small wrapper around the surface, so the
reversal buffer never limited hardware decoding. Hardware frames are now
estimated from their frames context (format and size).

Measured on an UHD 60 fps single-GOP H.264 clip played backward from 2.5 s with
VideoToolbox (Apple M5 Pro, `vmmap`): with a 1 GiB reversal buffer the process
held **2.1 GB** of IOSurfaces (203 surfaces) before the patch and **1.1 GB**
(100–111 surfaces) after. These surfaces do not appear in the process's
physical footprint, so the growth was also invisible there.

## 0008: overflowing batches thin evenly instead of jumping

When a batch did not fit, mpv discarded its newest frames, which are shown
first, so playback jumped over them (2.5 s straight to 1.25 s in the clip
above). Video batches that do not fit now keep every second frame, then every
fourth and so on, so reverse playback stays continuous at a reduced frame rate.
`--msg-level=vd=v` logs `Reversal queue full, keeping every N. frame.`

Same clip, 1 GiB buffer: time-pos falls steadily (2.5, 2.4, 2.2, 1.93, ...
0.27) at real-time speed, at 15 fps instead of 60. With 4 GiB the batch fits
and plays at full rate as before. Audio keeps mpv's existing behaviour.

## Consequences for applications

With 0007 the configured buffer now also applies to hardware decoding. A
buffer sized for software frames can be smaller than the long-GOP UHD batches
VideoToolbox previously held without limit; 0008 then reduces the frame rate
instead of jumping. Size the buffer for the largest batch that should still
play at full rate, e.g. a 2 s GOP of UHD 10-bit at 60 fps is about 3 GB.

## Not reproduced

"Backward playback is likely stuck/broken now" was not reproduced with
synthetic HEVC that changes its PPS mid-stream (parameter sets in-band, mp4
and mkv, software and VideoToolbox). Ordinary multi-GOP H.264/HEVC with and
without B-frames reverses without timestamp warnings. A sample file that
triggers it is needed to investigate further.
