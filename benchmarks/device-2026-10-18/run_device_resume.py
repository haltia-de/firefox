#!/usr/bin/env python3
"""B8000-H Wayland benchmark. Uses only disposable copies of a saved profile."""
import argparse
import gc
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import statistics
import subprocess
import threading
import time
import traceback
import urllib.parse

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'calibration-profile'
TICKS = os.sysconf('SC_CLK_TCK')
BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
HARNESS_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
KEYS = ['dom.ipc.processCount', 'fission.autostart', 'layout.frame_rate',
        'dom.ipc.processPrelaunch.enabled', 'general.config.filename',
        'image.mem.surfacecache.size_factor', 'browser.tabs.unloadOnLowMemory',
        'browser.tabs.min_inactive_duration_before_unload',
        'browser.low_commit_space_threshold_percent', 'browser.low_commit_space_threshold_mb',
        'browser.cache.disk.enable', 'javascript.options.ion']
VARIANTS = {
    'installed': [],
    'baseline': [],
    'factor8': ['--image-cache-factor', '8'],
    'factor16': ['--image-cache-factor', '16'],
    'fps30': ['--fps', '30'],
    'inactive30': ['--unload-after', '30'],
    'threshold15': ['--unload-after', '30', '--unload-threshold-percent', '15'],
    'threshold25': ['--unload-after', '30', '--unload-threshold-percent', '25'],
}


def emit(**data):
    print(json.dumps({'time': time.time(), **data}), flush=True)


def system_memory():
    return {key: int(value.split()[0]) for key, value in
            (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}


def snapshot(root):
    processes = {}
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            fields = (path / 'stat').read_text().rsplit(') ', 1)[1].split()
            processes[int(path.name)] = {'pid': int(path.name), 'ppid': int(fields[1]),
                'start': fields[19], 'ticks': int(fields[11]) + int(fields[12])}
        except (OSError, ValueError):
            pass
    owned = {root}
    while True:
        expanded = owned | {pid for pid, p in processes.items() if p['ppid'] in owned}
        if expanded == owned:
            break
        owned = expanded
    result = []
    for pid in sorted(owned):
        if pid not in processes:
            continue
        item = processes[pid]
        try:
            for line in Path('/proc', str(pid), 'smaps_rollup').read_text().splitlines():
                key, _, value = line.partition(':')
                if key in ['Pss', 'SwapPss', 'Rss']:
                    item[key] = int(value.split()[0])
            result.append(item)
        except OSError:
            pass
    mem = system_memory()
    return {'time': time.time(), 'processes': result,
            'totals_kib': {key: sum(p.get(key, 0) for p in result)
                           for key in ['Pss', 'SwapPss', 'Rss']},
            'available_kib': mem['MemAvailable'],
            'system_swap_used_kib': mem['SwapTotal'] - mem['SwapFree']}


def cpu_delta(before, after):
    old = {(p['pid'], p['start']): p['ticks'] for p in before['processes']}
    return sum(p['ticks'] - old[(p['pid'], p['start'])] for p in after['processes']
               if (p['pid'], p['start']) in old) / TICKS


class Marionette:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), 2)
        self.socket.settimeout(150)
        self.next_id = 0
        self.hello = self.receive()

    def receive(self):
        length = b''
        while not length.endswith(b':'):
            chunk = self.socket.recv(1)
            if not chunk:
                raise EOFError('Marionette closed')
            length += chunk
        size = int(length[:-1])
        data = b''
        while len(data) < size:
            chunk = self.socket.recv(size - len(data))
            if not chunk:
                raise EOFError('Marionette closed mid-message')
            data += chunk
        return json.loads(data)

    def command(self, name, params=None):
        self.next_id += 1
        data = json.dumps([0, self.next_id, name, params or {}]).encode()
        self.socket.sendall(str(len(data)).encode() + b':' + data)
        response = self.receive()
        if response[1] != self.next_id:
            raise ValueError('Marionette sequence mismatch')
        if response[2]:
            raise RuntimeError(response[2])
        return response[3]

    def script(self, text, chrome=False, async_=False, args=None):
        self.command('Marionette:SetContext', {'value': 'chrome' if chrome else 'content'})
        value = self.command('WebDriver:ExecuteAsyncScript' if async_ else 'WebDriver:ExecuteScript',
                             {'script': text, 'args': args or [], 'newSandbox': False,
                              'sandbox': 'default' if chrome else None, 'scriptTimeout': 120000})
        return value.get('value') if isinstance(value, dict) and 'value' in value else value

    def close(self):
        self.socket.close()


PARAGRAPH = '<p>' + ('A deterministic paragraph for ARM browser measurements. ' * 24) + '</p>'


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path.startswith('/image-') and parsed.path.endswith('.jpg'):
            path = HERE / 'fixtures' / Path(parsed.path).name
            data, mime = path.read_bytes(), 'image/jpeg'
        elif parsed.path == '/favicon.ico':
            data, mime = b'', 'image/x-icon'
        else:
            tab = urllib.parse.parse_qs(parsed.query).get('tab', ['0'])[0]
            body = ''.join(PARAGRAPH + f'<img src="/image-{i:02d}.jpg?tab={tab}" '
                           'width="1200" height="900">' for i in range(16))
            data = ('<!doctype html><html><head><meta charset="utf-8"><title>ARM fixture</title>'
                    '<style>body{font:18px sans-serif;max-width:900px;margin:auto;background:white;'
                    'color:#222}img{width:900px;height:675px}p{line-height:1.5}</style></head><body>'
                    '<article><h1>Deterministic device fixture</h1><input id="form">' + body +
                    '</article><script>window.payload=new Float64Array(1024*1024);'
                    'for(let i=0;i<payload.length;i+=512)payload[i]=i;'
                    'window.__ready=true;</script></body></html>').encode()
            mime = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public,max-age=3600')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def session_environment():
    env = dict(os.environ, XDG_RUNTIME_DIR='/run/user/1000', WAYLAND_DISPLAY='wayland-0',
               MOZ_ENABLE_WAYLAND='1', GDK_BACKEND='wayland')
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if (path / 'comm').read_text().strip() == 'b8k-home':
                fields = dict(s.split(b'=', 1) for s in
                              (path / 'environ').read_bytes().split(b'\0') if b'=' in s)
                for key in ['DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR', 'WAYLAND_DISPLAY']:
                    if key.encode() in fields:
                        env[key] = fields[key.encode()].decode()
        except OSError:
            pass
    return env


def make_profile(run_id, variant):
    home = HERE / 'runs' / run_id / 'home'
    profile = home / '.config/mozilla/firefox/b8k.default'
    shutil.copytree(SOURCE, profile, ignore=shutil.ignore_patterns(
        'lock', '.parentlock', 'parent.lock', 'cache2', 'startupCache', 'sessionstore*',
        'sessionCheckpoints.json', 'minidumps', 'crashes', 'datareporting',
        'saved-telemetry-pings'))
    env = dict(os.environ, HOME=str(home))
    subprocess.run(['/usr/bin/b8k-firefox-profile', '--reset-optimizations', '--shell',
                    *VARIANTS[variant]], env=env, check=True, capture_output=True)
    settings = {'marionette.port': 2828, 'remote.prefs.recommended': False,
                'browser.startup.page': 0, 'browser.startup.homepage': 'about:blank',
                'browser.sessionstore.resume_session_once': False,
                'browser.sessionstore.resume_from_crash': False,
                'browser.shell.checkDefaultBrowser': False,
                'network.proxy.type': 1, 'network.proxy.http': '127.0.0.1',
                'network.proxy.http_port': 9, 'network.proxy.ssl': '127.0.0.1',
                'network.proxy.ssl_port': 9, 'network.proxy.no_proxies_on': 'localhost,127.0.0.1'}
    with (profile / 'user.js').open('a') as stream:
        for key, value in settings.items():
            stream.write('\nuser_pref(' + json.dumps(key) + ', ' + json.dumps(value) + ');')
        stream.write('\n')
    return home, profile


def tabs(driver):
    return driver.script('return [...gBrowser.tabs].map(t=>({pending:t.hasAttribute("pending"),'
                         'selected:t===gBrowser.selectedTab,age:Date.now()-t.lastAccessed}));', True)


def trusted_activity(driver):
    # The Linux memory watcher pauses when user interaction becomes inactive.
    # Keep only the selected fixture active through normal WebDriver input.
    driver.command('Marionette:SetContext', {'value': 'content'})
    driver.command('WebDriver:PerformActions', {'actions': [{'type': 'pointer',
        'id': 'memory-probe-mouse', 'parameters': {'pointerType': 'mouse'}, 'actions': [
            {'type': 'pointerMove', 'duration': 0, 'origin': 'viewport', 'x': 500, 'y': 500},
            {'type': 'pointerDown', 'button': 0}, {'type': 'pointerUp', 'button': 0}]}]})


def pressure_probe(driver, pid, percent, threshold_mb):
    # Match bg-tab ages, then approach a real 10/15% threshold. Keep swap
    # reserve and stop below 80 MiB available. Never force huge pref values.
    driver.script('for(const t of [...gBrowser.tabs]) gBrowser.selectedTab=t; return true;', True)
    time.sleep(36)
    trusted_activity(driver)
    result = {'before': snapshot(pid), 'tabs_before': tabs(driver), 'target_percent': percent,
              'threshold_mb': threshold_mb, 'samples': [], 'allocated_mib': 0}
    chunks = []
    try:
        mem = system_memory()
        target = max(mem['MemTotal'] * percent / 100, threshold_mb * 1024) - 8 * 1024
        result['target_available_kib'] = target
        for _ in range(128):
            mem = system_memory()
            if mem['MemAvailable'] <= target:
                break
            if mem['MemAvailable'] < 80 * 1024 or mem['SwapFree'] < mem['SwapTotal'] * .3:
                result['guard'] = 'low_available_or_swap'
                break
            chunk = bytearray(4 * 1024 * 1024)
            for offset in range(0, len(chunk), 4096):
                chunk[offset:offset+4] = (offset // 4096 + len(chunks) * 1024).to_bytes(4, 'little')
            chunks.append(chunk)
            result['allocated_mib'] += 4
            time.sleep(.025)
        result['threshold_approached'] = system_memory()['MemAvailable'] <= target
        for _ in range(10):
            trusted_activity(driver)
            state = snapshot(pid)
            result['samples'].append({'memory': state, 'tabs': tabs(driver)})
            mem = system_memory()
            if mem['MemAvailable'] < 80 * 1024 or mem['SwapFree'] < mem['SwapTotal'] * .3:
                result['guard'] = 'low_available_or_swap'
                break
            time.sleep(2)
    finally:
        chunks.clear()
        if 'chunk' in locals():
            del chunk
        gc.collect()
    time.sleep(7)
    result['after_release'] = snapshot(pid)
    result['tabs_after'] = tabs(driver)
    return result


def run(variant, repeat, port, pressure=False):
    run_id = ('pressure-' if pressure else 'main-') + f'{variant}-{repeat}'
    result = {'variant': variant, 'repeat': repeat, 'pressure_run': pressure,
              'started': time.time(), 'status': 'running', 'boot_id': BOOT_ID,
              'harness_sha256': HARNESS_SHA256}
    proc, driver = None, None
    emit(event='start', run=run_id)
    try:
        home, profile = make_profile(run_id, variant)
        env = session_environment()
        env['HOME'] = str(home)
        log = open(HERE / 'runs' / run_id / 'firefox.log', 'w')
        binary = '/usr/lib/firefox/firefox' if variant == 'installed' else str(HERE / 'firefox-app/firefox')
        result['binary'] = binary
        proc = subprocess.Popen([binary, '--no-remote', '--profile',
            str(profile), '--marionette', '--remote-allow-system-access', 'about:blank'],
            env=env, stdout=log, stderr=log, start_new_session=True)
        result['pid'] = proc.pid
        for _ in range(180):
            if proc.poll() is not None:
                raise RuntimeError('Firefox exited before Marionette')
            try:
                driver = Marionette(2828)
                break
            except OSError:
                time.sleep(.5)
        if driver is None:
            raise TimeoutError('Marionette did not start')
        result['capabilities'] = driver.command('WebDriver:NewSession', {})['capabilities']
        driver.command('WebDriver:SetTimeouts', {'script': 120000, 'pageLoad': 120000})
        result['runtime'] = driver.script('''let prefs={};for(const k of arguments[0]){
          switch(Services.prefs.getPrefType(k)){
          case 128:prefs[k]=Services.prefs.getBoolPref(k);break;
          case 64:prefs[k]=Services.prefs.getIntPref(k);break;
          case 32:prefs[k]=Services.prefs.getStringPref(k);break;}}
          return {abi:Services.appinfo.XPCOMABI,version:Services.appinfo.version,prefs,
          gfx:Cc['@mozilla.org/gfx/info;1'].getService(Ci.nsIGfxInfo).getFeatures(),
          policy:Services.policies.status,
          ubOL:!!WebExtensionPolicy.getByID('uBOLiteRedux@raymondhill.net')};''', True, args=[KEYS])
        if not result['runtime']['ubOL']:
            time.sleep(10)
            result['runtime']['ubOL'] = driver.script(
                "return !!WebExtensionPolicy.getByID('uBOLiteRedux@raymondhill.net');", True)
        assert result['runtime']['ubOL'], 'uBOL inactive'
        result['session_ready_seconds'] = time.time() - result['started']
        emit(event='session_ready', run=run_id, seconds=result['session_ready_seconds'])
        handles, fixture = [], []
        driver.command('Marionette:SetContext', {'value': 'content'})
        for index in range(3):
            if index:
                handle = driver.command('WebDriver:NewWindow', {'type': 'tab'})['handle']
                driver.command('WebDriver:SwitchToWindow', {'handle': handle})
            else:
                handle = driver.command('WebDriver:GetWindowHandle')['value']
            handles.append(handle)
            driver.command('Marionette:SetContext', {'value': 'content'})
            driver.command('WebDriver:Navigate', {'url': f'http://127.0.0.1:{port}/article?tab={index}'})
            decoded = driver.script('''let done=arguments[arguments.length-1];
              Promise.allSettled([...document.images].map(i=>i.decode())).then(a=>done({
                ready:window.__ready===true,images:document.images.length,
                decoded:a.filter(x=>x.status==='fulfilled').length,
                width:innerWidth,height:innerHeight,visibility:document.visibilityState}));''', async_=True)
            fixture.append(decoded)
            assert decoded['ready'] and decoded['decoded'] == 16, decoded
            emit(event='tab_decoded', run=run_id, tab=index, decoded=decoded['decoded'])
        result['fixture'] = fixture
        time.sleep(7)
        result['loaded_samples'] = [snapshot(proc.pid)]
        for _ in range(2):
            time.sleep(1)
            result['loaded_samples'].append(snapshot(proc.pid))
        result['tabs_loaded'] = tabs(driver)
        if pressure:
            result['pressure'] = pressure_probe(driver, proc.pid,
                result['runtime']['prefs']['browser.low_commit_space_threshold_percent'],
                result['runtime']['prefs']['browser.low_commit_space_threshold_mb'])
        else:
            before = snapshot(proc.pid)
            result['scroll'] = driver.script('''let done=arguments[arguments.length-1],n=0,
              start=performance.now();function frame(t){n++;scrollTo(0,((t-start)*3)%
              (document.documentElement.scrollHeight-innerHeight));if(t-start<8000)
              requestAnimationFrame(frame);else done({frames:n,elapsed:t-start,
              visibility:document.visibilityState});}requestAnimationFrame(frame);''', async_=True)
            after = snapshot(proc.pid)
            result['scroll']['cpu_seconds'] = cpu_delta(before, after)
            result['scroll']['before'] = before
            result['scroll']['after'] = after
            time.sleep(7)
            result['before_discard'] = snapshot(proc.pid)
            result['discard'] = driver.script('return [...gBrowser.tabs].map(t=>'
                't===gBrowser.selectedTab?false:gBrowser.discardBrowser(t));', True)
            time.sleep(7)
            result['after_discard'] = snapshot(proc.pid)
            result['tabs_after_discard'] = tabs(driver)
            driver.command('Marionette:SetContext', {'value': 'content'})
            driver.command('WebDriver:SwitchToWindow', {'handle': handles[0]})
            time.sleep(3)
            result['restored'] = driver.script('return {ready:window.__ready===true,'
                'images:document.images.length,location:location.href};')
            assert result['restored']['ready'] and result['restored']['images'] == 16
            assert result['restored']['location'].endswith('?tab=0'), result['restored']
        result['status'] = 'ok'
    except Exception:
        result['status'] = 'error'
        result['error'] = traceback.format_exc()
    finally:
        if driver:
            try:
                driver.close()
            except OSError as exc:
                result['connection_close_error'] = str(exc)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                diagnostic = {}
                for name in ['stat', 'wchan', 'status']:
                    try:
                        diagnostic[name] = Path('/proc', str(proc.pid), name).read_text()
                    except OSError as exc:
                        diagnostic[name] = str(exc)
                result['termination_timeout'] = diagnostic
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    result['status'] = 'error'
                    result['cleanup_error'] = repr(exc)
            except OSError as exc:
                result['status'] = 'error'
                result['cleanup_error'] = repr(exc)
        result['finished'] = time.time()
        (HERE / 'results').mkdir(exist_ok=True)
        (HERE / 'results' / f'{run_id}.json').write_text(json.dumps(result, indent=2) + '\n')
        emit(event='finish', run=run_id, status=result['status'],
             seconds=result['finished']-result['started'], error=result.get('error'))
        # No profile data is transferred to the host. Keep logs/results and
        # the initial backup; delete only this run's disposable home.
        if 'home' in locals() and (proc is None or proc.poll() is not None):
            shutil.rmtree(home)
        gc.collect()
        time.sleep(3)
    return result['status'] == 'ok'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--variants', default='baseline,factor8,factor16,fps30')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--pressure', action='store_true')
    args = parser.parse_args()
    variants = args.variants.split(',')
    assert all(v in VARIANTS for v in variants)
    from b8k_compat.awake import Awake, logind_inhibit
    # The SSH session may inhibit idle, but not sleep. Keeping the display
    # awake prevents this tablet's idle-off -> suspend sequence without root.
    awake = Awake('Firefox validation', 'Temporary browser performance measurement',
                  inhibit=lambda what, who, why, mode: logind_inhibit('idle', who, why, mode))
    held = awake.hold()
    emit(event='inhibitor', held=held)
    if not held:
        raise SystemExit('Cannot inhibit idle; refusing timed rendering measurements')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for repeat in range(args.repeats):
            order = variants if repeat % 2 == 0 else list(reversed(variants))
            for variant in order:
                existing = HERE / 'results' / (('pressure-' if args.pressure else 'main-')
                                               + f'{variant}-{repeat}.json')
                if existing.exists() and json.loads(existing.read_text()).get('status') == 'ok':
                    emit(event='skip_completed', run=existing.stem)
                    continue
                guard_path = HERE / 'guard-state.json'
                if guard_path.exists():
                    guard = json.loads(guard_path.read_text())
                    if not guard.get('active') or time.time() - guard['time'] > 90:
                        raise SystemExit('Independent idle guard is not active')
                if not run(variant, repeat, server.server_port, args.pressure):
                    raise SystemExit('Run failed; stopping matrix for investigation')
    finally:
        server.shutdown()
        awake.release()
    emit(event='complete')


if __name__ == '__main__':
    main()
