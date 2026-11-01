#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepare immutable macOS GPL assets, the editor's FFmpeg helpers and a manifest patch; does not publish.

The helpers are the arm64 ffmpeg/ffprobe from the same FFmpeg configure run as the
Libav* archives, so an app that links the libraries and ships the helpers carries one
FFmpeg build. The helpers are staged unsigned; sign-editor-helpers.sh signs, notarizes
and zips them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

LIBRARIES = ['Libmpv', 'Libavcodec', 'Libavdevice', 'Libavfilter', 'Libavformat',
             'Libavutil', 'Libswresample', 'Libswscale', 'Libx264']
COMPONENT = {'Libmpv': 'libmpv', 'Libx264': 'libx264'}
KIND_SUFFIX = {'encoders': 'ENCODER', 'decoders': 'DECODER', 'filters': 'FILTER', 'muxers': 'MUXER', 'demuxers': 'DEMUXER'}
# Spot checks that the decoder/demuxer allow-lists are gone, not just widened.
EVERYTHING = ['THEORA_DECODER', 'MSMPEG4V3_DECODER', 'WAVPACK_DECODER', 'PIXLET_DECODER',
              'R3D_DEMUXER', 'IVF_DEMUXER', 'WV_DEMUXER', 'RAWVIDEO_DEMUXER', 'LAVFI_INDEV']
SYSTEM_PREFIXES = ('/usr/lib/', '/System/Library/')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def configuration(config_h):
    match = re.search(r'#define FFMPEG_CONFIGURATION "((?:[^"\\]|\\.)*)"', config_h)
    assert match, 'FFMPEG_CONFIGURATION missing'
    return match[1].encode().decode('unicode_escape')


def required_components(path):
    """Every component the editor lists, optional ones included, as alternative configure names:
    listings call the raw PCM formats `f32le`, configure `pcm_f32le`; input devices are indevs."""
    document = json.loads(path.read_text())
    names = set()
    for feature in document['features'].values():
        for kind, suffix in KIND_SUFFIX.items():
            for name in feature.get(kind, []) + feature.get('optional' + kind.capitalize(), []):
                alternatives = [f'{name.upper()}_{suffix}']
                if kind in ('muxers', 'demuxers'):
                    alternatives.append(f'PCM_{name.upper()}_{suffix}')
                if kind == 'demuxers':
                    alternatives.append(f'{name.upper()}_INDEV')
                names.add(tuple(alternatives))
    return names


def sources_archive(tag):
    return f'mpvkit-{tag.removeprefix("aagedal-1.1.0-")}-sources.tar.gz'


def package_sources(root, build, x264, provenance, archive):
    """The fork at HEAD, the exact (patched) FFmpeg, mpv and x264 sources and the configurations."""
    assert not subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain'], text=True).strip(), \
        'Commit the recipe first: the sources archive records HEAD'
    with tempfile.TemporaryDirectory() as staging:
        tree = Path(staging) / 'build'
        tree.mkdir()
        exported = subprocess.Popen(['git', '-C', str(root), 'archive', 'HEAD'], stdout=subprocess.PIPE)
        subprocess.run(['tar', '-x', '-C', str(tree)], stdin=exported.stdout, check=True)
        exported.stdout.close()
        assert exported.wait() == 0
        for source in [build / 'dist/FFmpeg-n9.0.2', build / 'dist/libmpv-v0.41.0', x264]:
            shutil.copytree(source, tree / 'dist' / source.name, ignore=shutil.ignore_patterns('.git'))
        shutil.copytree(provenance, tree / 'provenance')
        with tarfile.open(archive, 'w:gz') as package:
            package.add(tree, arcname='build')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--requirements', type=Path, required=True,
                        help="The editor's Configuration/FFmpegRequirements.json")
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9._-]+', args.tag): parser.error('Invalid release tag')
    root = Path(__file__).resolve().parents[1]
    build, output = args.candidate.resolve(), args.output.resolve()
    rebuild = json.loads((build / 'rebuild.json').read_text())
    assert rebuild['standalone_programs'] is True and rebuild.get('build_exit_code') == 0
    needed = required_components(args.requirements) | {(f'{name}_FILTER',) for name in ['ASTATS', 'ASETNSAMPLES', 'EBUR128']}
    needed |= {(name,) for name in EVERYTHING}
    # Check compiled configuration, not just the requested command-line flags.
    configurations = {}
    for arch in ['arm64', 'x86_64']:
        scratch = build / f'dist/FFmpeg/macos/scratch/{arch}'
        components = (scratch / 'config_components.h').read_text()
        missing = sorted(names[0] for names in needed if not any(f'#define CONFIG_{name} 1' in components for name in names))
        assert not missing, (arch, missing)
        config_h = (scratch / 'config.h').read_text()
        for flag in ['GPL', 'VERSION3', 'LIBX264']:
            assert f'#define CONFIG_{flag} 1' in config_h, (arch, flag)
        assert '#define CONFIG_NONFREE 0' in config_h, arch
        configurations[arch] = configuration(config_h)
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
        component = COMPONENT.get(library, 'FFmpeg')
        binary = build / f'dist/{component}/macos' / info[0]['BinaryPath']
        architectures = subprocess.check_output(['lipo', '-archs', str(binary)], text=True).split()
        assert set(architectures) == {'arm64', 'x86_64'}
        load_commands = subprocess.check_output(['otool', '-l', str(binary)], text=True)
        minimums = re.findall(r'^\s+(?:minos|version) (\d+(?:\.\d+)+)\s*$', load_commands, re.MULTILINE)
        assert minimums, library
        assert all(tuple(map(int, value.split('.'))) <= (12, 0, 0) for value in minimums), (library, set(minimums))
        asset = output / (library + '-GPL.xcframework.zip')
        shutil.copyfile(original_archive, asset)
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
                          'binary_sha256': digest(binary), 'binary_bytes': binary.stat().st_size,
                          'architectures': architectures, 'object_minimum_os_versions': sorted(set(minimums))})
    (output / 'Package.swift').write_text(manifest)

    # The editor helpers: arm64 programs from the arm64 libraries' own configure run.
    scratch = build / 'dist/FFmpeg/macos/scratch/arm64'
    helpers = output / 'ffmpeg-helpers'
    helpers.mkdir()
    configured = configurations['arm64'].encode()
    helper_report = {}
    for name in ['ffmpeg', 'ffprobe']:
        source = scratch / name
        assert subprocess.check_output(['lipo', '-archs', str(source)], text=True).split() == ['arm64'], name
        linked = subprocess.check_output(['otool', '-L', str(source)], text=True).splitlines()[1:]
        linked = [line.strip().split(' (compatibility')[0] for line in linked if line.strip()]
        assert all(item.startswith(SYSTEM_PREFIXES) for item in linked), (name, linked)
        assert configured in source.read_bytes(), f'{name} does not embed the arm64 library configuration'
        shutil.copyfile(source, helpers / name)
        (helpers / name).chmod(0o755)
        helper_report[name] = {'unsigned_sha256': digest(helpers / name), 'bytes': source.stat().st_size, 'dependencies': linked}
    libavcodec = build / 'dist/FFmpeg/macos/thin/arm64/lib/libavcodec.a'
    assert configured in libavcodec.read_bytes(), 'libavcodec.a does not embed the same configuration'
    sources = rebuild['source_revisions']
    x264 = build / 'dist' / next(p.name for p in (build / 'dist').iterdir() if p.name.startswith('libx264-'))
    sources['libx264'] = subprocess.check_output(['git', '-C', str(x264), 'rev-parse', 'HEAD'], text=True).strip()
    shutil.copyfile(build / 'dist/FFmpeg-n9.0.2/COPYING.GPLv3', helpers / 'COPYING.GPLv3')
    shutil.copyfile(build / 'dist/FFmpeg-n9.0.2/LICENSE.md', helpers / 'FFmpeg-LICENSE.md')
    shutil.copyfile(x264 / 'COPYING', helpers / 'x264-COPYING')
    shutil.copyfile(root / 'LICENSE', helpers / 'MPVKit-LICENSE')
    build_record = {'tag': args.tag, 'ffmpeg': 'n9.0.2', 'architecture': 'arm64', 'minimum_os': '12.0',
                    'licence': 'GPL version 3 or later, no nonfree', 'configuration': configurations['arm64'],
                    'source_revisions': sources, 'mpvkit_commit': subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip(),
                    'libavcodec_arm64_sha256': digest(libavcodec), 'helpers': helper_report}
    (helpers / 'build.json').write_text(json.dumps(build_record, indent=2) + '\n')
    (helpers / 'README.md').write_text(f'''# FFmpeg n9.0.2 helpers ({args.tag})

Static arm64 `ffmpeg` and `ffprobe` for Aagedal Film Constructor, built by the same
FFmpeg configure run as the `Libav*-GPL` frameworks of this MPVKit release. An app that
links those frameworks and ships these helpers therefore carries one FFmpeg build.
`build.json` records the exact configuration, source revisions and hashes; the
configuration string is also embedded in both executables and in `libavcodec.a`.

- FFmpeg n9.0.2 ({sources['FFmpeg']}), GPL version 3 or later, no nonfree components
- x264 stable {sources['libx264'][:12]} (H.264 encoder), dav1d, uavs3d, libplacebo/MoltenVK,
  lcms2, libass/FreeType/HarfBuzz/FriBidi, GnuTLS/Nettle/GMP, libsmbclient, linked statically
- Minimum macOS 12.0, Apple Silicon only; linked against system libraries only
- Every FFmpeg decoder and demuxer; the encoders, filters and muxers the editor uses
  (see Configuration/FFmpegRequirements.json in the editor repository)

Corresponding source: `{sources_archive(args.tag)}` in the same release (patched
FFmpeg/mpv sources, x264 at the pinned revision, the build recipe and configurations).
Licences: `COPYING.GPLv3`, `FFmpeg-LICENSE.md`, `x264-COPYING`, `MPVKit-LICENSE`.
''')
    # Byte-for-byte input configurations and source patches accompany the release.
    provenance = output / 'provenance'; provenance.mkdir()
    for arch in ['arm64', 'x86_64']:
        for name in ['config.h', 'config_components.h', 'ffbuild/config.mak']:
            source = build / f'dist/FFmpeg/macos/scratch/{arch}' / name
            shutil.copyfile(source, provenance / f'ffmpeg-{arch}-{source.name}')
        shutil.copyfile(build / f'dist/libmpv/macos/scratch/{arch}/meson-info/intro-buildoptions.json',
                        provenance / f'mpv-{arch}-buildoptions.json')
        shutil.copyfile(build / f'dist/libx264/macos/scratch/{arch}/config.h', provenance / f'x264-{arch}-config.h')
    shutil.copytree(root / 'Sources/BuildScripts/patch', provenance / 'patches')
    package_sources(root, build, x264, provenance, output / sources_archive(args.tag))
    report = {'tag': args.tag, 'platform': 'macos', 'minimum_os': '12.0', 'gpl': True,
              'native_scopes': False, 'artifacts': artifacts, 'helpers': build_record}
    (output / 'release.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
