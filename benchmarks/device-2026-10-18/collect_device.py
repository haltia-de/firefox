#!/usr/bin/env python3
"""Fetch generated JSON results, keeping profiles and browser data on device."""
import json
from pathlib import Path
import statistics
import subprocess

HERE = Path(__file__).resolve().parent
(HERE / 'results').mkdir(exist_ok=True)
subprocess.run(['scp', '-q', '-o', 'ConnectTimeout=8', '-o', 'ServerAliveInterval=5',
                '-o', 'ServerAliveCountMax=2',
                'user@b8000h:.local/state/b8k-firefox-validation/results/*.json',
                str(HERE / 'results')], check=True, timeout=25)
subprocess.run(['python3', str(HERE / 'summarize_device.py')],
               check=True, stdout=subprocess.DEVNULL)
data = json.loads((HERE / 'summary.json').read_text())
out = {'saved_runs': len(data['rows']), 'groups': {}, 'same_boot_balanced_rounds': {}}
for variant, group in data['groups'].items():
    out['groups'][variant] = {'n': group['n'],
        'memory_mib': round(group['loaded_pss_swap_mib']['median'], 1)}
for variant in ['installed', 'baseline', 'factor8', 'factor16', 'fps30']:
    rows = [r for r in data['rows'] if r['variant'] == variant and r['repeat'] >= 2
            and not r['pressure'] and r['boot_id'] != 'before-reboot']
    if rows:
        out['same_boot_balanced_rounds'][variant] = {
            'n': len(rows),
            'memory_mib': round(statistics.median(r['loaded_pss_swap_mib'] for r in rows), 1),
            'cpu_per_8s': round(statistics.median(r['scroll_cpu_per_8s'] for r in rows), 2),
            'raf_hz': round(statistics.median(r['raf_hz'] for r in rows), 1)}
print(json.dumps(out, indent=2))
