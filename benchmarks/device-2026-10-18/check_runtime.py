#!/usr/bin/env python3
"""Real Firefox regression check: report default and effective b8k prefs."""
import json
import argparse
import re
from pathlib import Path
import subprocess
import time
from run_device import Marionette, session_environment

EXPECTED = {
    'browser.tabs.unloadOnLowMemory': True,
    'browser.tabs.min_inactive_duration_before_unload': 60000,
    'general.config.filename': 'b8k-firefox.cfg',
    'dom.ipc.processPrelaunch.enabled': False,
}
parser = argparse.ArgumentParser()
parser.add_argument('--binary', default='/usr/lib/firefox/firefox')
parser.add_argument('--all-defaults', action='store_true')
args = parser.parse_args()
if args.all_defaults:
    base = Path(args.binary).resolve().parent
    for name in ['b8k-ram.js', 'b8k-lean.js', 'zz-b8k-firefox.js']:
        candidates = [base / 'browser/defaults/preferences' / name,
                      base / 'defaults/pref' / name]
        path = next(p for p in candidates if p.exists())
        EXPECTED.update({k: json.loads(v) for k, v in re.findall(
            r'^pref\("([^"\n]+)",\s*(true|false|-?\d+|"[^"\n]*")\);',
            path.read_text(), re.M)})
lab = Path(__file__).resolve().parent
proc = subprocess.Popen([args.binary, '--no-remote', '--profile',
    str(lab / 'calibration-profile'), '--marionette', '--remote-allow-system-access', 'about:blank'],
    env=session_environment(), stdout=open(lab / 'runtime-check.log', 'a'),
    stderr=subprocess.STDOUT)
m = None
try:
    for _ in range(180):
        if proc.poll() is not None:
            raise RuntimeError('Firefox exited')
        try:
            m = Marionette(2828)
            break
        except OSError:
            time.sleep(.5)
    if m is None:
        raise TimeoutError('Firefox did not start')
    m.command('WebDriver:NewSession', {})
    actual = m.script('''let d=Services.prefs.getDefaultBranch(''),r={};
      for(let k of arguments[0]){let typ=Services.prefs.getPrefType(k),
      f=typ===128?'getBoolPref':typ===64?'getIntPref':'getStringPref';
      r[k]={value:Services.prefs[f](k),defaultValue:d[f](k),
      user:Services.prefs.prefHasUserValue(k),locked:Services.prefs.prefIsLocked(k)};}
      return r;''', True, args=[list(EXPECTED)])
    field = 'defaultValue' if args.all_defaults else 'value'
    mismatches = {key: {'expected': value, 'actual': actual[key]}
                  for key, value in EXPECTED.items() if actual[key][field] != value}
    print(json.dumps({'prefs': actual, 'mismatches': mismatches,
                      'checked': len(EXPECTED), 'comparison_field': field,
                      'status': 'fail' if mismatches else 'pass'}, indent=2))
    raise SystemExit(bool(mismatches))
finally:
    if m:
        m.close()
    proc.terminate()
    proc.wait(timeout=30)
