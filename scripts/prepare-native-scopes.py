#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply the opt-in mpv 0.41.0 native scope source closure after MPVKit patches.

Checks the entire patch before writing. Recognizes an exactly applied patch;
rejects partial/modified applications. No downloads, dependency builds or package
publication happen here. The Swift build recipe restricts this to GPL macOS arm64.
"""
import argparse
from pathlib import Path
import subprocess


def prepare(source, check_only=False):
    patch = Path(__file__).resolve().parents[1] / 'Sources/BuildScripts/experimental/native-scopes/mpv-0.41.0-native-scopes.patch'
    def check(reverse=False):
        return subprocess.run(['git','-C',str(source),'apply','--check'] +
                              (['--reverse'] if reverse else []) + [str(patch)],
                              capture_output=True,text=True)
    if check(reverse=True).returncode == 0:
        print('Native scope source closure already applied.')
        return
    forward = check()
    if forward.returncode:
        raise ValueError('Expected mpv v0.41.0 with the standard MPVKit patches, or an exact previous application.\n'+forward.stderr)
    if check_only:
        print('Native scope source closure applies cleanly.')
    else:
        subprocess.run(['git','-C',str(source),'apply',str(patch)],check=True)
        print('Applied native scopes, default-off decoder-raster prerequisite, and retained CoreAudio source fixes.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('--check',action='store_true')
    a=p.parse_args()
    try:prepare(a.source,a.check)
    except (ValueError,subprocess.CalledProcessError) as error:p.exit(1,str(error)+'\n')
