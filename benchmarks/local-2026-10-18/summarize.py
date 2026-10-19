#!/usr/bin/env python3
"""Summarize raw browser samples. PSS is Firefox-tree-only, in MiB."""
import csv
import json
import os
from pathlib import Path
import statistics

ROOT = Path(__file__).parent


def phase_median(samples, key='Pss'):
    if not samples:
        return None
    return statistics.median(s['totals'].get(key, 0) for s in samples) / 1024


def summarize_run(r):
    phases = r.get('phases', {})
    out = {'variant': r['variant'], 'repeat': r['repeat'], 'status': r['status'],
           'error': r.get('error'), 'suite': r.get('suite', 'screening'),
           'duration_s': r['ended'] - r['started']}
    for name, samples in phases.items():
        out[name+'_pss_mib'] = phase_median(samples)
        out[name+'_swap_pss_mib'] = phase_median(samples, 'SwapPss')
    if r.get('start'):
        out['start_pss_mib'] = phase_median(r['start'])
    if phases.get('three_tabs'):
        out['processes'] = statistics.median(s['count'] for s in phases['three_tabs'])
    if r.get('raf'):
        out['raf_hz'] = r['raf']['frames'] / (r['raf']['elapsed'] / 1000)
    out['animation_cpu_s'] = r.get('animation_cpu_seconds')
    if phases.get('idle'):
        a, b = phases['idle'][0], phases['idle'][-1]
        ticks = b['totals'].get('ticks', 0) - a['totals'].get('ticks', 0)
        out['idle_cpu_s'] = ticks/os.sysconf('SC_CLK_TCK') if ticks >= 0 else None
    out['fixture'] = r.get('fixture')
    out['tab_state'] = r.get('tab_state')
    if r.get('javascript'):
        # First call is warm-up, separate from the five measured evaluations.
        out['js_ms'] = statistics.median(v['ms'] for v in r['javascript'][1:])
        out['checksums'] = sorted(set(v['checksum'] for v in r['javascript']))
    return out


raw = []
for folder in ['runs', 'focused-memory', 'focused-image-stress', 'focused-cpu']:
    directory = ROOT/folder
    if directory.exists():
        for file in sorted(directory.glob('*.json')):
            raw.append(summarize_run(json.loads(file.read_text())))
groups = {}
for r in raw:
    groups.setdefault((r['suite'], r['variant']), []).append(r)
summary = []
for (suite, variant), runs in sorted(groups.items()):
    row = {'suite': suite, 'variant': variant, 'n': len(runs),
           'ok': sum(r['status'] == 'ok' for r in runs)}
    for key in sorted(set().union(*(r.keys() for r in runs))):
        values = [r[key] for r in runs if isinstance(r.get(key), (float, int)) and key != 'repeat']
        if values:
            row[key] = statistics.median(values)
            row[key+'_min'] = min(values)
            row[key+'_max'] = max(values)
    summary.append(row)
(ROOT/'summary.json').write_text(json.dumps({'runs': raw, 'groups': summary}, indent=2)+'\n')
fields = ['suite','variant','n','ok','start_pss_mib','one_tab_pss_mib','three_tabs_pss_mib',
          'three_tabs_pss_mib_min','three_tabs_pss_mib_max','after_action_pss_mib',
          'after_back_pss_mib','processes','raf_hz','animation_cpu_s','idle_cpu_s','js_ms']
with (ROOT/'summary.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
    writer.writeheader();writer.writerows(summary)
for row in summary:
    print(row['suite'],row['variant'],row['ok'],'/',row['n'],
          'pss',round(row['three_tabs_pss_mib'],1) if 'three_tabs_pss_mib' in row else '-',
          'action',round(row['after_action_pss_mib'],1) if 'after_action_pss_mib' in row else '-',
          'js',round(row['js_ms'],1) if 'js_ms' in row else '-')
