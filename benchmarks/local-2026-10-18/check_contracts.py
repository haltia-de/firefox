#!/usr/bin/env python3
"""Check policy/profile/install contracts inside the isolated Alpine container."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path('/work')
OUT = Path('/results')
checks = []


def record(name, status, evidence):
    checks.append({'name': name, 'status': status, 'evidence': evidence})


for filename in ['install.sh', 'b8k-firefox-configure', 'b8k-firefox-profile',
                 'packaging/alpine/APKBUILD', 'packaging/alpine/b8k-firefox.post-install',
                 'packaging/alpine/b8k-firefox.post-upgrade']:
    p = subprocess.run(['sh', '-n', str(ROOT / filename)], capture_output=True, text=True)
    record('syntax:' + filename, 'pass' if p.returncode == 0 else 'fail', p.stderr)
ast.parse((ROOT / 'b8k-policies.py').read_text())
record('syntax:python', 'pass', 'ast.parse')

with tempfile.TemporaryDirectory(prefix='b8k-contract-') as tmp:
    tmp = Path(tmp)
    source, dest = tmp/'source.json', tmp/'policies.json'
    source.write_text(json.dumps({'policies': {'DisableTelemetry': True,
        'ExtensionSettings': {'other@test': {'installation_mode': 'allowed'}}}}))
    subprocess.run(['python3', str(ROOT/'b8k-policies.py'), str(source), str(dest),
                    '/usr/share/b8k-firefox/ubol.xpi', '/usr/share/b8k-firefox/langpack-ru.xpi'], check=True)
    p = json.loads(dest.read_text())['policies']
    assert p['DisableTelemetry'] and 'other@test' in p['ExtensionSettings']
    assert p['3rdparty']['Extensions']['uBOLiteRedux@raymondhill.net']['defaultFiltering'] == 'complete'
    record('policy-preservation', 'pass', p)

    # Use the container user's actual home. No host browser profile is touched.
    home = Path.home()
    subprocess.run(['sh', str(ROOT/'b8k-firefox-profile'), '--shell'], check=True)
    profile = home/'.config/mozilla/firefox/b8k.default'
    a = {str(f.relative_to(profile)): hashlib.sha256(f.read_bytes()).hexdigest()
         for f in profile.rglob('*') if f.is_file()}
    subprocess.run(['sh', str(ROOT/'b8k-firefox-profile'), '--shell'], check=True)
    b = {str(f.relative_to(profile)): hashlib.sha256(f.read_bytes()).hexdigest()
         for f in profile.rglob('*') if f.is_file()}
    assert a == b
    record('profile-idempotence', 'pass', a)
    subprocess.run(['sh', str(ROOT/'b8k-firefox-profile')], check=True)
    assert 'padding-inline-end: 110px' not in (profile/'chrome/userChrome.css').read_text()
    record('profile-shell-toggle', 'pass', 'Shell padding removed by regular profile run')
    userjs = profile/'user.js'
    userjs.write_text(userjs.read_text().replace('"dom.ipc.processCount", 1', '"dom.ipc.processCount", 2'))
    subprocess.run(['sh', str(ROOT/'b8k-firefox-profile')], check=True)
    lines = [l for l in userjs.read_text().splitlines() if 'dom.ipc.processCount"' in l]
    record('profile-experiment-override', 'finding', lines)

    # Offline staged installer with preverified real pinned XPI. Stub only the
    # unused language-pack download; this is an explicit missing-download case.
    fake = tmp/'root'
    ff = fake/'usr/lib/firefox'
    (ff/'distribution').mkdir(parents=True)
    (ff/'application.ini').write_text('[App]\nVersion=151.0.3\n')
    (ff/'distribution/policies.json').write_text(source.read_text())
    cache = tmp/'cache'; cache.mkdir()
    (cache/'uBOLite_2026.1012.1545.firefox.signed.xpi').write_bytes((OUT/'ubol.xpi').read_bytes())
    stub = tmp/'bin'; stub.mkdir()
    (stub/'wget').write_text('#!/bin/sh\nexit 1\n'); (stub/'wget').chmod(0o755)
    env = dict(os.environ, PATH=str(stub)+':'+os.environ['PATH'], B8K_CACHE=str(cache))
    proc = subprocess.run(['sh', str(ROOT/'install.sh'), str(fake), '/usr'],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    policy_path = fake/'etc/firefox/policies/policies.json'
    installed = json.loads(policy_path.read_text())['policies']['ExtensionSettings']
    before = installed['uBOLiteRedux@raymondhill.net']['install_url']
    # The packaged post-install entry point has a different __dirname.
    subprocess.run(['sh', str(fake/'usr/share/b8k-firefox/b8k-firefox-configure')],
                   env=dict(env, ROOT=str(fake)), check=True, capture_output=True)
    after = json.loads(policy_path.read_text())['policies']['ExtensionSettings'][
        'uBOLiteRedux@raymondhill.net']['install_url']
    record('installer-source-vs-installed-configure', 'finding' if before != after else 'pass', {
        'ubol_file_exists': (fake/'usr/share/b8k-firefox/ubol.xpi').exists(),
        'source_configure_url': before, 'installed_configure_url': after,
        'installer_exit': proc.returncode, 'stderr': proc.stderr})
    record('missing-langpack-download', 'pass', 'Installer continues without missing XPI, as implemented')

(OUT/'contracts.json').write_text(json.dumps(checks, indent=2)+'\n')
for result in checks:
    print(result['name'], result['status'])
