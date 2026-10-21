#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Maintain our user.js block; leave manual overrides after it intact."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tempfile

# The markers keep the name before ADR 0004: they are in people's user.js.
BEGIN = '// BEGIN b8k-firefox managed prefs\n'
END = '// END b8k-firefox managed prefs\n'
BASE = {
    'toolkit.legacyUserProfileCustomizations.stylesheets': True,
    'browser.tabs.tabClipWidth': 1,
    'browser.tabs.tabMinWidth': 240,
}
LEGACY = dict(BASE, **{
    'dom.ipc.processCount': 1,
    'dom.ipc.processCount.webIsolated': 1,
    'fission.autostart': False,
    'dom.ipc.keepProcessesAlive.web': 0,
    'browser.sessionstore.resume_from_crash': False,
    'browser.startup.page': 1,
})
OPTIONS = {
    'image_cache_factor': 'image.mem.surfacecache.size_factor',
    'fps': 'layout.frame_rate',
    'unload_after': 'browser.tabs.min_inactive_duration_before_unload',
    'unload_threshold_percent': 'browser.low_commit_space_threshold_percent',
}


def pref(key, value):
    return f'user_pref({json.dumps(key)}, {json.dumps(value)});\n'


def atomic_write(path, text):
    """Replace path with text. A crash keeps the previous file."""
    path = os.fspath(path)
    directory = os.path.dirname(path) or '.'
    fd, tmp = tempfile.mkstemp(prefix='.haltia-', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        mode = 0o644
        if os.path.lexists(path):
            mode = os.lstat(path).st_mode & 0o777
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_changed(path, text):
    if not path.exists() or path.read_text() != text:
        atomic_write(path, text)


def update(profile, args):
    path = profile / 'user.js'
    text = path.read_text() if path.exists() else ''
    values = dict(BASE)
    malformed = False
    if BEGIN in text or END in text:
        # A raise here exits under the profile loop's set -eu and skips
        # every profile after this one. Leave this file alone.
        counts_wrong = text.count(BEGIN) != 1 or text.count(END) != 1
        end_before_begin = BEGIN in text and END not in text.split(BEGIN, 1)[1]
        if counts_wrong or end_before_begin:
            print(f'{path}: malformed b8k-firefox block', file=sys.stderr)
            malformed = True
        else:
            before, block = text.split(BEGIN, 1)
            block, after = block.split(END, 1)
            # Read only the generated format, never execute JavaScript.
            for key in OPTIONS.values():
                match = re.search(r'^user_pref\(' + re.escape(json.dumps(key))
                                  + r', (\d+)\);$', block, re.M)
                if match:
                    values[key] = int(match[1])
            text = before + after
    if not malformed:
        # Migrate the exact lines emitted by the old shell tool. Non-default
        # manual settings survive, including processCount=2 and startup.page=0.
        legacy = {pref(key, value).rstrip('\n') for key, value in LEGACY.items()}
        text = ''.join(line for line in text.splitlines(keepends=True)
                       if line.rstrip('\r\n') not in legacy)
        if args.reset_optimizations:
            for key in OPTIONS.values():
                values.pop(key, None)
        for option, key in OPTIONS.items():
            value = getattr(args, option)
            if value is not None:
                values[key] = value * 1000 if option == 'unload_after' else value
        managed = BEGIN + ''.join(pref(key, value) for key, value in values.items()) + END
        write_changed(path, managed + text)
    if args.reset_optimizations:
        # Removing user.js lines alone does not reset persisted Firefox prefs.
        # This explicit reset also removes these four keys from prefs.js.
        # Firefox holds <profile>/lock (a symlink whose target does not exist)
        # while it runs and rewrites prefs.js as it exits.
        persisted = profile / 'prefs.js'
        if persisted.exists():
            if (profile / 'lock').lexists():
                print(f'{persisted}: Firefox is running; not changing prefs.js',
                      file=sys.stderr)
            else:
                pattern = re.compile(r'^user_pref\("(?:' + '|'.join(
                    re.escape(key) for key in OPTIONS.values()) + r')",.*\);\s*$')
                write_changed(persisted, ''.join(
                    line for line in persisted.read_text().splitlines(keepends=True)
                    if not pattern.fullmatch(line.rstrip('\r\n'))))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--shell', action='store_true', help='Use tablet-shell toolbar CSS')
    parser.add_argument('--image-cache-factor', type=int, choices=(8, 16))
    parser.add_argument('--fps', type=int, choices=(30, 60))
    parser.add_argument('--unload-after', type=int, metavar='SECONDS',
                        help='Minimum inactive tab age, not an unload timer (1..3600)')
    parser.add_argument('--unload-threshold-percent', type=int, metavar='PERCENT',
                        help='Available memory threshold (1..50); tune on the device')
    parser.add_argument('--reset-optimizations', action='store_true',
                        help='Clear optional overrides in user.js and prefs.js')
    parser.add_argument('--profile', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--check', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    for name, maximum in [('unload_after', 3600), ('unload_threshold_percent', 50)]:
        value = getattr(args, name)
        if value is not None and not 1 <= value <= maximum:
            parser.error(f'--{name.replace("_", "-")} must be between 1 and {maximum}')
    if args.check:
        return
    if args.profile is None:
        parser.error('--profile is required internally')
    update(args.profile, args)


if __name__ == '__main__':
    main()
