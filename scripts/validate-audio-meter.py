#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a linked mpv_audio_meter_probe against independent PCM signal fixtures.

Pass a probe linked against the candidate's complete FFmpeg/libmpv set. The
probe also verifies runtime filter removal and subsequent exact seek/restart.
No screen/audio capture permission, external tools or physical output is needed.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import wave

PEAKS = '@meter:lavfi=[asetnsamples=n=480:p=0,astats=metadata=1:reset=1:measure_perchannel=Peak_level+RMS_level:measure_overall=Peak_level+RMS_level]'
LOUDNESS = '@meter:lavfi=[ebur128=metadata=1:peak=true]'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('probe', type=Path)
    parser.add_argument('output', type=Path, help='New directory for fixtures/results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    results = []
    for name, amplitudes in [('mono', [0.25]), ('stereo', [0.25, 0.5]),
                             ('surround', [0.125, 0.25, 0.375, 0.5, 0.625, 0.75]),
                             ('silence', [0, 0])]:
        fixture = args.output / (name + '.wav')
        # Exactly 1 kHz at 48 kHz gives exact peaks and complete 10 ms periods.
        with wave.open(str(fixture), 'wb') as output:
            output.setnchannels(len(amplitudes)); output.setsampwidth(2); output.setframerate(48000)
            output.writeframes(b''.join(struct.pack('<' + 'h' * len(amplitudes),
                *(round(a * 32767 * math.sin(2 * math.pi * i / 48)) for a in amplitudes))
                for i in range(48000 * 4)))
        for kind, graph in [('peaks', PEAKS), ('loudness', LOUDNESS)]:
            run = subprocess.run([str(args.probe.resolve()), str(fixture.resolve()), graph],
                                 capture_output=True, text=True, timeout=20)
            (args.output / (name + '-' + kind + '.log')).write_text(run.stdout + run.stderr)
            if run.returncode: raise RuntimeError(f'{name}/{kind}: probe exit {run.returncode}')
            payload = json.loads(next(line for line in run.stdout.splitlines() if line.startswith('{')))
            metadata = payload['metadata']
            if kind == 'peaks':
                for index, amplitude in enumerate(amplitudes, 1):
                    peak = float(metadata[f'lavfi.astats.{index}.Peak_level'])
                    rms = float(metadata[f'lavfi.astats.{index}.RMS_level'])
                    if amplitude:
                        assert abs(peak - 20 * math.log10(amplitude)) < 0.03, (name, index, peak)
                        assert abs(rms - (20 * math.log10(amplitude) - 3.0103)) < 0.03, (name, index, rms)
                    else:
                        assert peak == -math.inf and rms == -math.inf
                assert sum(key.endswith('.Peak_level') and '.Overall.' not in key for key in metadata) == len(amplitudes)
            else:
                for key in ['lavfi.r128.M', 'lavfi.r128.S', 'lavfi.r128.I', 'lavfi.r128.true_peak']:
                    assert key in metadata and math.isfinite(float(metadata[key])), (name, key, metadata)
                assert abs(float(metadata['lavfi.r128.true_peak']) - max(amplitudes)) < 0.003
                if name in ['mono', 'stereo']:
                    expected = 10 * math.log10(sum(a * a for a in amplitudes) / 2)
                    assert abs(float(metadata['lavfi.r128.M']) - expected) < 0.15
                    assert abs(float(metadata['lavfi.r128.I']) - expected) < 0.15
                elif name == 'silence':
                    assert float(metadata['lavfi.r128.M']) < -100
            results.append({'signal': name, 'analysis': kind, **payload})
    (args.output / 'report.json').write_text(json.dumps({'passed': True, 'results': results}, indent=2) + '\n')
    print(f'AUDIO_METER_ACCEPTANCE: {len(results)} signal/filter cases passed')


if __name__ == '__main__': main()
