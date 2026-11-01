#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stage an isolated macOS GPL FFmpeg/libmpv rebuild from an existing dependency cache.

Only the new output directory is changed. Auxiliary dependency outputs remain
read-only inputs. Source revisions are checked against the recipe's version tags;
source patches are reapplied to clean exports, never inferred from cached edits.
The library payloads use the normal recipe. Standalone CLI programs are omitted
unless --programs is given, which keeps the arm64 ffmpeg/ffprobe that the
editor ships as its media helpers (same configure run as the libraries).
x264 is built from its pinned source, since no prebuilt dependency exists.
"""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def export(source, destination):
    destination.mkdir()
    archive = subprocess.Popen(['git', '-C', str(source), 'archive', 'HEAD'], stdout=subprocess.PIPE)
    subprocess.run(['tar', '-x', '-C', str(destination)], stdin=archive.stdout, check=True)
    archive.stdout.close()
    if archive.wait(): raise RuntimeError('Source export failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-root', type=Path, required=True, help='MPVKit checkout with built dist dependencies')
    parser.add_argument('--output', type=Path, required=True, help='New staging directory')
    parser.add_argument('--build', action='store_true')
    parser.add_argument('--programs', action='store_true', help='Also build ffmpeg/ffprobe for the editor helpers')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cache, output = args.cache_root.resolve() / 'dist', args.output.resolve()
    recipe = (root / 'Sources/BuildScripts/XCFrameworkBuild/main.swift').read_text()
    libraries = []
    for library in ['FFmpeg', 'libmpv']:
        match = re.search(r'case \.' + library + r':\s*return "([^"]+)"', recipe)
        if not match:
            parser.error(f'Cannot read {library} version from build recipe')
        libraries.append((library, match[1]))
    revisions = {}
    for library, version in libraries:
        source = cache / (library + '-' + version)
        revision = git(source, 'rev-parse', 'HEAD')
        if revision != git(source, 'rev-parse', version + '^{commit}'):
            parser.error(f'{source} is not at {version}')
        revisions[library] = revision
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(root / 'Sources', output / 'Sources')
    shutil.copytree(root / 'scripts', output / 'scripts')
    shutil.copytree(root / 'docs', output / 'docs')
    (output / 'dist').mkdir()
    for child in cache.iterdir():
        if child.is_dir() and child.name not in ['FFmpeg', 'libmpv', 'release', 'libx264'] and not child.name.startswith(('FFmpeg-', 'libmpv-', 'libx264-')):
            (output / 'dist' / child.name).symlink_to(child, target_is_directory=True)
    for library, version in libraries:
        destination = output / 'dist' / (library + '-' + version)
        export(cache / destination.name, destination)
        for patch in sorted((root / 'Sources/BuildScripts/patch' / library).glob('*.patch')):
            subprocess.run(['git', 'apply', str(patch)], cwd=destination, check=True)
    entrypoint = output / 'Sources/BuildScripts/XCFrameworkBuild/main.swift'
    text = entrypoint.read_text()
    start, end = text.index('    // SSL\n'), text.index('    try BuildMPV().buildALL()')
    text = text[:start] + '    try BuildX264().buildALL()\n    try BuildFFMPEG().buildALL()\n' + text[end:]
    if not args.programs:
        text = text.replace('if platform == .macos, arch.executable {', 'if false {')
    text = text.replace('''        if !(platform == .macos && arch.executable) {
            array.append("-Dcplayer=false")
        }''', '        array.append("-Dcplayer=false")')
    entrypoint.write_text(text)
    base = output / 'Sources/BuildScripts/XCFrameworkBuild/base.swift'
    text = base.read_text().replace('        task.environment = environment', '''        for key in ["TMPDIR", "CLANG_MODULE_CACHE_PATH"] {
            if let value = ProcessInfo.processInfo.environment[key] { environment[key] = value }
        }
        task.environment = environment''')
    base.write_text(text)
    report = {'source_revisions': revisions, 'cache': str(cache), 'output': str(output),
              'platform': 'macos', 'architectures': ['arm64', 'x86_64'], 'gpl': True,
              'standalone_programs': args.programs, 'native_scopes': False}
    if args.build:
        with (output / 'build.log').open('w') as log:
            run = subprocess.run(['swift', 'run', '--disable-sandbox', '--build-path', '.build',
                '--package-path', 'Sources/BuildScripts', 'build', 'platform=macos', 'enable-gpl'],
                cwd=output, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT)
        report['build_exit_code'] = run.returncode
    (output / 'rebuild.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if args.build: raise SystemExit(run.returncode)


if __name__ == '__main__': main()
