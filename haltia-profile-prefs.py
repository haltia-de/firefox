#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Maintain our user.js block; leave manual overrides after it intact."""
import argparse
import json
from pathlib import Path
import re

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


def write_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def update(profile, args):
    path = profile / 'user.js'
    text = path.read_text() if path.exists() else ''
    values = dict(BASE)
    if BEGIN in text or END in text:
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise ValueError(f'{path}: malformed b8k-firefox block')
        before, block = text.split(BEGIN)
        block, after = block.split(END)
        # Read only the generated format, never execute JavaScript.
        for key in OPTIONS.values():
            match = re.search(r'^user_pref\(' + re.escape(json.dumps(key))
                              + r', (\d+)\);$', block, re.M)
            if match:
                values[key] = int(match[1])
        text = before + after
    # Migrate the exact lines emitted by the old shell tool. Non-default
    # manual settings survive, including processCount=2 and startup.page=0.
    legacy = {pref(key, value).rstrip('\n') for key, value in LEGACY.items()}
    text = ''.join(line for line in text.splitlines(keepends=True)
                   if line.rstrip('\r\n') not in legacy)
    if args.reset_optimizations:
        for key in OPTIONS.values():
            values.pop(key, None)
        # Removing user.js lines alone does not reset persisted Firefox prefs.
        # This explicit reset also removes these four keys from prefs.js.
        persisted = profile / 'prefs.js'
        if persisted.exists():
            pattern = re.compile(r'^user_pref\("(?:' + '|'.join(
                re.escape(key) for key in OPTIONS.values()) + r')",.*\);\s*$')
            write_changed(persisted, ''.join(
                line for line in persisted.read_text().splitlines(keepends=True)
                if not pattern.fullmatch(line.rstrip('\r\n'))))
    for option, key in OPTIONS.items():
        value = getattr(args, option)
        if value is not None:
            values[key] = value * 1000 if option == 'unload_after' else value
    managed = BEGIN + ''.join(pref(key, value) for key, value in values.items()) + END
    write_changed(path, managed + text)


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
