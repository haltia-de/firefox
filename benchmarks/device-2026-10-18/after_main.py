#!/usr/bin/env python3
"""Run the pressure screen only after a successful, finished main matrix."""
from pathlib import Path
import json
import subprocess
import time
from b8k_compat.awake import Awake, logind_inhibit

HERE = Path(__file__).resolve().parent
awake = Awake('Firefox validation continuation', 'Serial benchmark phases',
              inhibit=lambda what, who, why, mode: logind_inhibit('idle', who, why, mode))
assert awake.hold(), 'Cannot keep the tablet awake between benchmark phases'
pid = int((HERE / 'matrix.pid').read_text())
while True:
    path = Path('/proc', str(pid), 'stat')
    if not path.exists() or path.read_text().rsplit(') ', 1)[1].split()[0] == 'Z':
        break
    time.sleep(2)
results = list((HERE / 'results').glob('main-*.json'))
assert len(results) == 25 and all(json.loads(p.read_text())['status'] == 'ok' for p in results)
assert '"event": "complete"' in (HERE / 'matrix-main.log').read_text()
with (HERE / 'matrix-pressure-screen.log').open('w') as log:
    subprocess.run(['python3', '-u', str(HERE / 'run_device.py'), '--variants',
                    'baseline,inactive30,threshold15,threshold25', '--repeats', '1', '--pressure'],
                   stdout=log, stderr=log, check=True)
