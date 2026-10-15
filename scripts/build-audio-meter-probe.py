#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Link the audio acceptance probe against resolved candidate framework products."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--products', type=Path, required=True)
    parser.add_argument('--arch', choices=['arm64', 'x86_64'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    products = args.products.resolve()
    developer = subprocess.check_output(['xcode-select', '-p'], text=True).strip()
    swift = Path(developer) / 'Toolchains/XcodeDefault.xctoolchain/usr/lib/swift/macosx'
    source = Path(__file__).resolve().parents[1] / 'Tests/AudioMeter/mpv_audio_meter_probe.c'
    command = ['xcrun', 'clang', '-arch', args.arch, '-mmacosx-version-min=12.0', str(source),
               '-I' + str(products / 'Libmpv.framework/Headers'),
               '-I' + str(products / 'Libavfilter.framework/Headers'),
               '-F' + str(products), '-L' + str(products), '-L' + str(swift),
               '-o', str(args.output.resolve())]
    for framework in sorted(products.glob('*.framework')):
        if framework.stem != 'Sparkle': command += ['-framework', framework.stem]
    for name in ['AVFoundation', 'CoreAudio', 'AudioToolbox', 'CoreVideo', 'CoreFoundation',
                 'CoreMedia', 'Metal', 'VideoToolbox', 'AppKit']:
        command += ['-framework', name]
    command += ['-lMoltenVK', '-lbz2', '-liconv', '-lexpat', '-lresolv', '-lxml2', '-lz', '-lc++',
                '-Wl,-rpath,' + str(products), '-Wl,-rpath,/usr/lib/swift']
    subprocess.run(command, check=True)


if __name__ == '__main__': main()
