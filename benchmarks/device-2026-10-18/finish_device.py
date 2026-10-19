#!/usr/bin/env python3
"""Compare the user profile without restoring it, remove lab copies, release guard."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import tarfile
import time
from gi.repository import Gio, GLib

HERE = Path(__file__).resolve().parent
PROFILE = Path.home() / '.config/mozilla/firefox/b8k.default'
BACKUP = HERE / 'profile-before-20261018-194912.tar.gz'


def running():
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            state = (proc / 'stat').read_text().rsplit(') ', 1)[1].split()[0]
            comm = (proc / 'comm').read_text().lower()
        except (OSError, IndexError):
            continue
        if state == 'Z':
            continue
        try:
            executable = Path(os.readlink(proc / 'exe')).name
        except OSError:
            executable = ''
        if ('firefox' in comm
                or 'firefox' in executable
                or any(name in cmd for name in ['run_device_resume.py', 'run_device.py',
                                                'check_runtime.py', 'after_main.py'])):
            result.append({'pid': int(proc.name), 'cmdline': cmd, 'state': state})
    return result


def digest(stream):
    h = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        h.update(chunk)
    return h.hexdigest()


def verify_profile():
    expected = {}
    with tarfile.open(BACKUP) as archive:
        for member in archive:
            path = Path(member.name)
            assert path.parts[0] == PROFILE.name
            rel = str(Path(*path.parts[1:]))
            if member.isfile():
                expected[rel] = ['file', digest(archive.extractfile(member))]
            elif member.issym():
                expected[rel] = ['symlink', member.linkname]
            else:
                assert member.isdir(), f'Unexpected backup entry: {member.name}'
    actual = {}
    for path in PROFILE.rglob('*'):
        rel = str(path.relative_to(PROFILE))
        if path.is_symlink():
            actual[rel] = ['symlink', os.readlink(path)]
        elif path.is_file():
            with path.open('rb') as stream:
                actual[rel] = ['file', digest(stream)]
    differences = sorted(k for k in expected.keys() | actual.keys()
                         if expected.get(k) != actual.get(k))
    main_start = min(json.loads(line)['time'] for line in (HERE / 'matrix-main.log').read_text().splitlines()
                     if '"event": "start"' in line)
    difference_times = []
    for rel in differences:
        path = PROFILE / rel
        mtime = path.lstat().st_mtime if path.exists() or path.is_symlink() else None
        difference_times.append({'name': rel, 'mtime': mtime,
                                 'mtime_before_main': mtime < main_start if mtime else None})
    # Report names only; never export browser data or individual file hashes.
    return {'equal': not differences, 'entries': len(expected),
            'differences': differences, 'difference_times': difference_times,
            'main_started': main_start, 'backup_retained': BACKUP.exists(),
            'restored': False}


result = {'time': time.time(), 'running_before': running()}
assert not result['running_before'], result['running_before']
result['profile_comparison'] = verify_profile()
# An older backup may predate a later normal browser session. Never overwrite
# user data to manufacture equality; retain both the comparison and the backup.
result['removed'] = []
for path in [HERE / 'firefox-app', HERE / 'calibration-profile', HERE / 'runs']:
    assert path.parent == HERE and not path.is_symlink()
    if path.exists():
        shutil.rmtree(path)
        result['removed'].append(path.name)
guard_pid = int((HERE / 'guard.pid').read_text())
guard_proc = Path('/proc', str(guard_pid))
if guard_proc.exists() and b'hold_awake.py' in (guard_proc / 'cmdline').read_bytes():
    os.kill(guard_pid, signal.SIGTERM)
    for _ in range(50):
        state = json.loads((HERE / 'guard-state.json').read_text())
        if not state['active']:
            break
        time.sleep(.2)
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
rows = bus.call_sync('org.freedesktop.login1', '/org/freedesktop/login1',
    'org.freedesktop.login1.Manager', 'ListInhibitors', None,
    GLib.VariantType('(a(ssssuu))'), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
result['remaining_validation_inhibitors'] = [list(r) for r in rows
                                          if 'Firefox validation' in r[1]]
result['running_after'] = running()
result['status'] = 'pass' if not result['remaining_validation_inhibitors'] and not result['running_after'] else 'fail'
(HERE / 'cleanup.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
assert result['status'] == 'pass'
