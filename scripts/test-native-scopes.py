#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the CPU scope math tests (Tests/NativeScopes/scope_math_tests.c) under
ASan/UBSan against an mpv source tree with MPVKit's patches applied.

Only the libplacebo include directory (headers) is needed. No downloads, no
dependency build; nothing in the source tree is changed.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path, help='patched mpv source tree')
    p.add_argument('--placebo-include', type=Path, required=True)
    a = p.parse_args()
    if not (a.source / 'video/scope.c').exists():
        p.error(f'{a.source} lacks video/scope.c; apply Sources/BuildScripts/patch/libmpv first')
    with tempfile.TemporaryDirectory(prefix='mpv-scope-math-') as temp:
        executable = Path(temp) / 'scope-math-tests'
        subprocess.run(['clang', '-arch', 'arm64', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=undefined', '-I' + str(a.source / 'video'),
                        '-I' + str(a.placebo_include), str(root / 'Tests/NativeScopes/scope_math_tests.c'),
                        '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    main()
