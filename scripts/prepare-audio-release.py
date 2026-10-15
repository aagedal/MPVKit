#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare immutable macOS GPL assets and a manifest patch; does not publish."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import zipfile

LIBRARIES = ['Libmpv', 'Libavcodec', 'Libavdevice', 'Libavfilter', 'Libavformat',
             'Libavutil', 'Libswresample', 'Libswscale']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]+', args.tag): parser.error('Invalid release tag')
    root = Path(__file__).resolve().parents[1]
    build, output = args.candidate.resolve(), args.output.resolve()
    # Check compiled configuration, not just the requested command-line flags.
    for arch in ['arm64', 'x86_64']:
        config = (build / f'dist/FFmpeg/macos/scratch/{arch}/config_components.h').read_text()
        for feature in ['ASTATS', 'ASETNSAMPLES', 'EBUR128']:
            assert f'#define CONFIG_{feature}_FILTER 1' in config
        assert '#define CONFIG_GPL 1' in (build / f'dist/FFmpeg/macos/scratch/{arch}/config.h').read_text()
        options = json.loads((build / f'dist/libmpv/macos/scratch/{arch}/meson-info/intro-buildoptions.json').read_text())
        assert next(option['value'] for option in options if option['name'] == 'gpl') is True
        assert next(option['value'] for option in options if option['name'] == 'cplayer') is False
    output.mkdir(parents=True, exist_ok=False)
    manifest = (root / 'Package.swift').read_text()
    artifacts = []
    for library in LIBRARIES:
        original_archive = build / f'dist/release/{library}.xcframework.zip'
        with zipfile.ZipFile(original_archive) as archive:
            info = plistlib.loads(archive.read(library + '.xcframework/Info.plist'))['AvailableLibraries']
        assert len(info) == 1 and info[0]['SupportedPlatform'] == 'macos'
        assert set(info[0]['SupportedArchitectures']) == {'arm64', 'x86_64'}
        component = 'libmpv' if library == 'Libmpv' else 'FFmpeg'
        binary = build / f'dist/{component}/macos' / info[0]['BinaryPath']
        architectures = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
        assert set(architectures) == {'arm64', 'x86_64'}
        load_commands = subprocess.check_output(['otool', '-l', str(binary)], text=True)
        minimums = re.findall(r'^\s+(?:minos|version) (\d+(?:\.\d+)+)\s*$', load_commands, re.MULTILINE)
        assert minimums, library
        assert all(tuple(map(int, value.split('.'))) <= (12, 0, 0) for value in minimums), (library, set(minimums))
        asset = output / (library + '-GPL.xcframework.zip')
        shutil.copyfile(build / f'dist/release/{library}.xcframework.zip', asset)
        with zipfile.ZipFile(asset) as archive:
            binary_member = library + '.xcframework/' + info[0]['LibraryIdentifier'] + '/' + info[0]['BinaryPath']
            assert hashlib.sha256(archive.read(binary_member)).hexdigest() == digest(binary)
            assert archive.testzip() is None
        checksum = digest(asset)
        (output / (library + '-GPL.xcframework.checksum.txt')).write_text(checksum + '\n')
        pattern = r'(name: "' + library + r'-GPL",\s*url: ")[^"]+("\s*,\s*checksum: ")[^"]+("\s*\))'
        url = f'https://github.com/aagedal/MPVKit/releases/download/{args.tag}/{asset.name}'
        manifest, count = re.subn(pattern, lambda m: m[1] + url + m[2] + checksum + m[3], manifest)
        assert count == 1, library
        artifacts.append({'asset': asset.name, 'sha256': checksum, 'bytes': asset.stat().st_size,
                          'binary_sha256': digest(binary), 'architectures': architectures,
                          'object_minimum_os_versions': sorted(set(minimums))})
    (output / 'Package.swift').write_text(manifest)
    # Byte-for-byte input configurations and source patches accompany the release.
    provenance = output / 'provenance'; provenance.mkdir()
    for arch in ['arm64', 'x86_64']:
        for name in ['config.h', 'config_components.h', 'ffbuild/config.mak']:
            source = build / f'dist/FFmpeg/macos/scratch/{arch}' / name
            target = provenance / f'ffmpeg-{arch}-{source.name}'
            shutil.copyfile(source, target)
        shutil.copyfile(build / f'dist/libmpv/macos/scratch/{arch}/meson-info/intro-buildoptions.json',
                        provenance / f'mpv-{arch}-buildoptions.json')
    shutil.copytree(root / 'Sources/BuildScripts/patch', provenance / 'patches')
    report = {'tag': args.tag, 'platform': 'macos', 'minimum_os': '12.0',
              'filters': ['astats', 'asetnsamples', 'ebur128'], 'gpl': True,
              'native_scopes': False, 'artifacts': artifacts}
    (output / 'release.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
