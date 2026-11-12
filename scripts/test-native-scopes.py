#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Check patch application, idempotence, rejection and sanitized scope math.

Pass mpv v0.42.0 with MPVKit's existing standard patches applied, and the
libplacebo include directory (headers only). Only a new copy inside a temporary
directory is changed. No downloads or dependency build.
"""
import argparse
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('prepare',root/'scripts/prepare-native-scopes.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path)
    p.add_argument('--placebo-include',type=Path,required=True);a=p.parse_args()
    with tempfile.TemporaryDirectory(prefix='mpv-native-scope-test-') as temp:
        source=Path(temp)/'mpv';shutil.copytree(a.source,source,symlinks=True)
        module.prepare(source,check_only=True)
        module.prepare(source)
        before=(source/'video/scope.h').read_bytes()
        module.prepare(source)
        assert (source/'video/scope.h').read_bytes()==before
        executable=Path(temp)/'scope-math-tests'
        subprocess.run(['clang','-arch','arm64','-O1','-g','-fsanitize=address,undefined',
                        '-fno-sanitize-recover=undefined','-I'+str(source/'video'),
                        '-I'+str(a.placebo_include),str(root/'Tests/NativeScopes/scope_math_tests.c'),
                        '-o',str(executable)],check=True)
        subprocess.run([str(executable)],check=True)
        # A modified previous application cannot be treated as complete or reapplied.
        (source/'video/scope.h').write_bytes(before.replace(b'struct mp_scope_params',b'struct changed_scope_params',1))
        try:module.prepare(source)
        except ValueError:pass
        else:raise AssertionError('modified source was accepted')
        print('NATIVE_SCOPE_PATCH_ACCEPTANCE: apply/check/idempotence/modified-source rejection passed')


if __name__=='__main__':main()
