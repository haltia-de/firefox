#!/usr/bin/env python3
"""Temporary independent idle inhibitor, released on SIGTERM or after 2 hours."""
import json
import os
from pathlib import Path
import signal
import time
from gi.repository import Gio, GLib
from b8k_compat.awake import Awake, logind_inhibit

HERE = Path(__file__).resolve().parent
stopping = False


def stop(*args):
    global stopping
    stopping = True


for sig in [signal.SIGTERM, signal.SIGINT]:
    signal.signal(sig, stop)
awake = Awake('Firefox validation guard', 'Keep the display awake across test failures',
              inhibit=lambda what, who, why, mode: logind_inhibit('idle', who, why, mode))
assert awake.hold()
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
deadline = time.monotonic() + 7200
try:
    while not stopping and time.monotonic() < deadline:
        rows = bus.call_sync('org.freedesktop.login1', '/org/freedesktop/login1',
            'org.freedesktop.login1.Manager', 'ListInhibitors', None,
            GLib.VariantType('(a(ssssuu))'), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        own = [list(row) for row in rows if row[5] == os.getpid() and row[1] == awake.who]
        state = {'time': time.time(), 'pid': os.getpid(), 'active': bool(own), 'inhibitors': own}
        tmp = HERE / 'guard-state.tmp'
        tmp.write_text(json.dumps(state) + '\n')
        tmp.replace(HERE / 'guard-state.json')
        print(json.dumps(state), flush=True)
        if not own:
            raise SystemExit('Own logind inhibitor disappeared')
        for _ in range(30):
            if stopping:
                break
            time.sleep(1)
finally:
    awake.release()
    (HERE / 'guard-state.json').write_text(json.dumps(
        {'time': time.time(), 'pid': os.getpid(), 'active': False}) + '\n')
