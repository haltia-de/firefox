#!/usr/bin/env python3
"""Summarize only generated device results, never profile data."""
import csv
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
rows = []
for path in sorted((HERE / 'results').glob('*.json')):
    data = json.loads(path.read_text())
    if data['status'] != 'ok':
        continue
    samples = data['loaded_samples']
    row = {'run': path.stem, 'variant': data['variant'], 'repeat': data['repeat'],
           'boot_id': data.get('boot_id', 'before-reboot'),
           'pressure': data['pressure_run'],
           'loaded_pss_mib': statistics.median(s['totals_kib']['Pss']/1024 for s in samples),
           'loaded_pss_swap_mib': statistics.median(
               (s['totals_kib']['Pss']+s['totals_kib']['SwapPss'])/1024 for s in samples),
           'tabs_pending_loaded': sum(t['pending'] for t in data['tabs_loaded']),
           'session_ready_seconds': data['session_ready_seconds'],
           'total_seconds': data['finished']-data['started']}
    if not data['pressure_run']:
        before, after = data['before_discard']['totals_kib'], data['after_discard']['totals_kib']
        row.update(scroll_cpu_seconds=data['scroll']['cpu_seconds'],
                   scroll_cpu_per_8s=data['scroll']['cpu_seconds']*8000/data['scroll']['elapsed'],
                   scroll_elapsed_ms=data['scroll']['elapsed'],
                   raf_hz=data['scroll']['frames']/data['scroll']['elapsed']*1000,
                   before_discard_pss_swap_mib=(before['Pss']+before['SwapPss'])/1024,
                   after_discard_pss_swap_mib=(after['Pss']+after['SwapPss'])/1024,
                   discard_delta_mib=((after['Pss']+after['SwapPss'])-
                                      (before['Pss']+before['SwapPss']))/1024,
                   tabs_pending_after_discard=sum(t['pending'] for t in data['tabs_after_discard']),
                   restored_first=data['restored']['location'].endswith('?tab=0'))
    else:
        pressure = data['pressure']
        row.update(pressure_reached=pressure['threshold_approached'],
                   pressure_allocated_mib=pressure['allocated_mib'],
                   max_pending_pressure=max(sum(t['pending'] for t in s['tabs'])
                                            for s in pressure['samples']),
                   guard=pressure.get('guard'))
    rows.append(row)
summary = {}
for variant in sorted({r['variant'] for r in rows}):
    for pressure in [False, True]:
        group = [r for r in rows if r['variant'] == variant and r['pressure'] == pressure]
        if not group:
            continue
        item = {'n': len(group)}
        for key in group[0]:
            if key in ['repeat', 'pressure'] or isinstance(group[0][key], bool):
                continue
            values = [r[key] for r in group if isinstance(r.get(key), (int, float))]
            if values:
                item[key] = {'median': statistics.median(values),
                             'min': min(values), 'max': max(values)}
        summary[('pressure-' if pressure else '') + variant] = item
(HERE / 'summary.json').write_text(json.dumps({'groups': summary, 'rows': rows}, indent=2)+'\n')
if rows:
    with (HERE / 'summary.csv').open('w') as stream:
        writer = csv.DictWriter(stream, sorted({key for row in rows for key in row}))
        writer.writeheader()
        writer.writerows(rows)
print(json.dumps(summary, indent=2))
