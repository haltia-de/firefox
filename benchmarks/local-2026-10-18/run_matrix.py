#!/usr/bin/env python3
"""Isolated Firefox 151 / Alpine benchmark. Run inside the disposable lab container.

Uses stdlib WebDriver HTTP, loopback fixtures and fresh profiles. Never attaches
to an existing browser. See report for limitations; these are not ARM benchmarks.
"""
import argparse
import collections
import hashlib
import http.server
import json
import os
from pathlib import Path
import random
import re
import shutil
import socket
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = Path('/work')
OUT = Path('/results')
REQUESTS = []
LOCK = threading.Lock()


def read_prefs(text):
    return {m[0]: json.loads(m[1]) for m in re.findall(
        r'(?:user_)?pref\("([^"\n]+)",\s*(true|false|-?\d+|"[^"\n]*")\);', text)}


PROJECT = {}
for filename in ['b8k-ram.js', 'b8k-lean.js']:
    PROJECT.update(read_prefs((REPO / filename).read_text()))
PROJECT.update(read_prefs((REPO / 'b8k-firefox-profile').read_text()))
# The shell script contains both a legacy startup replacement and the final 1.
PROJECT['browser.startup.page'] = 1

COMMON = {
    'remote.prefs.recommended': False,
    'browser.shell.checkDefaultBrowser': False,
    'browser.startup.homepage_override.mstone': 'ignore',
    'browser.aboutwelcome.enabled': False,
    'browser.startup.firstrunSkipsHomepage': False,
    'browser.newtabpage.activity-stream.showWelcome': False,
    'app.update.auto': False,
    'datareporting.policy.dataSubmissionEnabled': False,
    'toolkit.telemetry.reportingpolicy.firstRun': False,
    'browser.warnOnQuitShortcut': False,
}

VARIANTS = {
    'project': {},
    'stock': {'stock': True, 'calm': 'none'},
    'no_lean': {'remove_lean': True},
    'images_factor8': {'prefs': {'image.mem.surfacecache.size_factor': 8}},
    'images_factor16': {'prefs': {'image.mem.surfacecache.size_factor': 16}},
    'images_cap64': {'prefs': {'image.mem.surfacecache.max_size_kb': 65536}},
    'images_cap128': {'prefs': {'image.mem.surfacecache.max_size_kb': 131072}},
    'images_expire5s': {'prefs': {'image.mem.surfacecache.min_expiration_ms': 5000}},
    'http_cache8': {'prefs': {'browser.cache.memory.capacity': 8192}},
    'http_cache16': {'prefs': {'browser.cache.memory.capacity': 16384}},
    'disk_cache_off': {'prefs': {'browser.cache.disk.enable': False}},
    'bfcache_auto': {'prefs': {'browser.sessionhistory.max_total_viewers': -1}},
    'processes2': {'prefs': {'dom.ipc.processCount': 2}},
    'fission_on': {'prefs': {'fission.autostart': True, 'dom.ipc.processCount.webIsolated': 1}},
    'prelaunch_on': {'prefs': {'dom.ipc.processPrelaunch.enabled': True}},
    'forkserver_off': {'prefs': {'dom.ipc.forkserver.enable': False}},
    'frame_rate30': {'prefs': {'layout.frame_rate': 30}},
    'no_images': {'prefs': {'permissions.default.image': 2}},
    'no_js': {'prefs': {'javascript.enabled': False}},
    'start_blank': {'start': 'about:blank', 'prefs': {'browser.startup.page': 0}},
    'calm_none': {'calm': 'none'},
    'calm_event': {'calm': 'event'},
    'unload_early': {'unload': True, 'prefs': {
        'browser.low_commit_space_threshold_mb': 65536,
        'browser.low_commit_space_threshold_percent': 10,
        'browser.tabs.min_inactive_duration_before_unload': 1000}},
    'betterfox': {'replace': 'betterfox.js'},
    'ubol_basic': {'extension': 'ubol', 'mode': 'basic'},
    'ubol_optimal': {'extension': 'ubol', 'mode': 'optimal'},
    'ubol_complete': {'extension': 'ubol', 'mode': 'complete'},
    'autotab': {'extension': 'autotab', 'extension_discard': True},
    'native_discard': {'discard': True},
    'reader': {'reader': True},
    'jit_off': {'prefs': {'javascript.options.baselinejit': False,
                          'javascript.options.ion': False}},
    'software_wr': {'prefs': {'gfx.webrender.software': True}},
}

CALM_EVENT = '''
(function () {
  function calm(win) {
    if (!win || win.closed || win.__b8kEventCalm) return;
    win.__b8kEventCalm = true;
    win.setTimeout(function () {
      if (win.closed || !win.gBrowser) return;
      const spec = win.gBrowser.selectedBrowser.currentURI.spec;
      if (/^about:(home|newtab|blank)(?:[?#]|$)/.test(spec)) {
        win.gURLBar.blur(); win.gBrowser.selectedBrowser.focus();
      }
    }, 0);
  }
  const obs = {observe(win) {calm(win);}};
  Services.obs.addObserver(obs, 'browser-delayed-startup-finished');
  for (const win of Services.wm.getEnumerator('navigator:browser')) {
    if (win.gBrowserInit?.delayedStartupFinished) calm(win);
  }
  globalThis.__b8kEventObserver = obs;
})();
'''

ARTICLE = '''<!doctype html><html><head><meta charset="utf-8"><title>Local article</title>
<style>body{font:18px sans-serif;max-width:900px;margin:auto;background:#fff;color:#222}
img{width:900px;height:675px;object-fit:contain}p{line-height:1.5}.ad{height:30px}
.moving{width:120px;height:25px;background:#86c;position:fixed;top:0;left:0;
animation:slide 2s linear infinite}@keyframes slide{50%{transform:translateX(500px)}}
@media(prefers-reduced-motion:reduce){.moving{animation:none}}</style></head><body>
<main><article><h1>A reproducible article for browser memory experiments</h1>
<p>This local document contains deterministic pictures, paragraphs and an optional script.
It tests resource mechanisms, not the behaviour of any production news website.</p>
<input id="form" aria-label="Test input"><div class="moving"></div>CONTENT</article></main>
<script src="/payload.js"></script></body></html>'''
CONTENT = ''.join(
    '<p>' + ('A paragraph of deterministic article text for measurement. ' * 18) +
    f'</p><img loading="eager" src="/image-{i:02d}.jpg" width="1200" height="900">'
    for i in range(16))
PAYLOAD = '''window.payload = new Float64Array(3 * 1024 * 1024);
for(let i=0;i<window.payload.length;i+=512) window.payload[i]=i;
const f=document.createDocumentFragment();
for(let i=0;i<1500;i++){let e=document.createElement('span');e.textContent=' node '+i;f.append(e);}
document.querySelector('article').append(f); window.__ready=true;'''


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if re.fullmatch(r'/image-\d\d\.jpg', path):
            body = (OUT / 'fixtures' / path[1:]).read_bytes()
            mime = 'image/jpeg'
        elif path == '/payload.js':
            body, mime = PAYLOAD.encode(), 'application/javascript'
        else:
            body, mime = ARTICLE.replace('CONTENT', CONTENT).encode(), 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'public,max-age=3600')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        with LOCK:
            REQUESTS.append({'path': path, 'bytes': len(body)})


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Driver:
    def __init__(self, profile, prefs, log):
        self.port, self.sid = free_port(), None
        self.log = open(log, 'w')
        self.proc = subprocess.Popen(
            ['geckodriver', '--host', '127.0.0.1', '--port', str(self.port),
             '--allow-system-access', '--log', 'warn'], stdout=self.log, stderr=self.log,
            start_new_session=True)
        try:
            for _ in range(100):
                try:
                    self.request('GET', '/status', timeout=1)
                    break
                except Exception:
                    if self.proc.poll() is not None:
                        raise RuntimeError('geckodriver exited')
                    time.sleep(.1)
            response = self.request('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'firefox', 'pageLoadStrategy': 'normal',
                'moz:firefoxOptions': {'binary': '/usr/lib/firefox/firefox',
                                      'args': ['--no-remote', '-profile', str(profile)],
                                      'prefs': prefs}}}}, timeout=90)
            self.sid = response['sessionId']
            self.caps = response['capabilities']
            self.pid = self.caps['moz:processID']
            self.call('POST', '/timeouts', {'script': 20000, 'pageLoad': 30000})
        except Exception:
            self.close()
            raise

    def request(self, method, path, body=None, timeout=40):
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}',
              data=json.dumps(body).encode() if body is not None else None,
              headers={'Content-Type': 'application/json'}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.load(response)['value']
        except urllib.error.HTTPError as err:
            raise RuntimeError(err.read().decode()) from err

    def call(self, method, path, body=None, timeout=40):
        return self.request(method, '/session/' + self.sid + path, body, timeout)

    def script(self, script, chrome=False, async_=False, args=None):
        self.call('POST', '/moz/context', {'context': 'chrome' if chrome else 'content'})
        return self.call('POST', '/execute/' + ('async' if async_ else 'sync'),
                         {'script': script, 'args': args or []})

    def navigate(self, url):
        self.call('POST', '/moz/context', {'context': 'content'})
        start = time.monotonic()
        self.call('POST', '/url', {'url': url})
        return time.monotonic() - start

    def close(self):
        if self.sid:
            try:
                self.call('DELETE', '', timeout=8)
            except Exception:
                pass
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, 15)
                self.proc.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.proc.pid, 9)
                except ProcessLookupError:
                    pass
        self.log.close()


def snapshot(pid):
    procs = {}
    for path in Path('/proc').glob('[0-9]*/stat'):
        try:
            text = path.read_text()
            end = text.rindex(')')
            parts = text[end + 2:].split()
            procs[int(path.parent.name)] = {
                'ppid': int(parts[1]), 'name': text[text.index('(') + 1:end],
                'ticks': int(parts[11]) + int(parts[12]), 'major_faults': int(parts[9])}
        except (OSError, ValueError, IndexError):
            pass
    selected = {pid}
    while True:
        found = {p for p, x in procs.items() if x['ppid'] in selected}
        if found <= selected:
            break
        selected |= found
    total = collections.Counter()
    details, unreadable = [], []
    for p in sorted(selected & procs.keys()):
        data = procs[p]
        memory = collections.Counter()
        try:
            for line in Path(f'/proc/{p}/smaps_rollup').read_text().splitlines():
                m = re.match(r'(Pss|SwapPss|Private_Dirty|Rss):\s+(\d+)', line)
                if m:
                    memory[m[1]] = int(m[2])
        except OSError as e:
            unreadable.append({'pid': p, 'error': str(e)})
        total.update(memory)
        total['ticks'] += data['ticks']
        total['major_faults'] += data['major_faults']
        details.append({'pid': p, **data, **memory})
    system = {}
    for filename in ['memory.current', 'memory.peak', 'memory.events', 'cpu.stat', 'memory.pressure']:
        path = Path('/sys/fs/cgroup') / filename
        if path.exists():
            system[filename] = path.read_text().strip()
    return {'at': time.time(), 'totals': dict(total), 'count': len(details),
            'processes': details, 'unreadable': unreadable, 'cgroup': system}


def samples(pid, duration=3):
    result = []
    until = time.monotonic() + duration
    while True:
        result.append(snapshot(pid))
        if time.monotonic() >= until:
            return result
        time.sleep(.5)


def prefs_script(keys):
    return '''return Object.fromEntries(arguments[0].map(k=>{
      let t=Services.prefs.getPrefType(k); let v=t===128?Services.prefs.getBoolPref(k):
      t===64?Services.prefs.getIntPref(k):t===32?Services.prefs.getStringPref(k):null;
      return [k,{type:t,value:v,user:Services.prefs.prefHasUserValue(k)}];}));'''


def configure(name, profile):
    spec = VARIANTS[name]
    prefs = {} if spec.get('stock') else dict(PROJECT)
    if spec.get('remove_lean'):
        for key in read_prefs((REPO / 'b8k-lean.js').read_text()):
            prefs.pop(key, None)
    if spec.get('replace'):
        prefs.update(read_prefs((OUT / spec['replace']).read_text()))
    prefs.update(COMMON)
    prefs.update(spec.get('prefs', {}))
    (profile / 'chrome').mkdir()
    if not spec.get('stock'):
        for name_css in ['userChrome.css', 'userContent.css']:
            shutil.copyfile(REPO / name_css, profile / 'chrome' / name_css)
    calm = spec.get('calm', 'poll')
    cfg = '// isolated b8k benchmark autoconfig\n'
    cfg += 'pref("b8k.bench.autoconfig", ' + json.dumps(calm) + ');\n'
    if calm == 'poll':
        cfg += (REPO / 'b8k-calm.js').read_text()
    elif calm == 'event':
        cfg += CALM_EVENT
    Path('/usr/lib/firefox/b8k-bench.cfg').write_text(cfg)
    policies = {'policies': {}}
    if spec.get('extension') == 'ubol':
        policies = {'policies': {
            'ExtensionSettings': {'uBOLiteRedux@raymondhill.net': {
                'installation_mode': 'force_installed', 'install_url': 'file:///results/ubol.xpi'}},
            '3rdparty': {'Extensions': {'uBOLiteRedux@raymondhill.net': {
                'defaultFiltering': spec['mode']}}}}}
    Path('/etc/firefox/policies/policies.json').write_text(json.dumps(policies))
    return prefs


def run_one(name, repeat, port, sample_seconds):
    spec = VARIANTS[name]
    run_id = f'{name}-{repeat}'
    profile = Path('/home/bench/lab') / run_id
    if profile.exists():
        shutil.rmtree(profile)
    profile.mkdir()
    prefs = configure(name, profile)
    result = {'variant': name, 'repeat': repeat, 'prefs_requested': prefs,
              'started': time.time(), 'phases': {}, 'load_seconds': []}
    driver = None
    with LOCK:
        REQUESTS.clear()
    try:
        start = time.monotonic()
        driver = Driver(profile, prefs, OUT / 'logs' / f'{run_id}.log')
        result['session_start_seconds'] = time.monotonic() - start
        result['capabilities'] = driver.caps
        driver.navigate(spec.get('start', 'about:home'))
        time.sleep(2)
        if spec.get('extension') == 'autotab':
            result['extension_install'] = driver.call('POST', '/moz/addon/install', {
                'path': '/results/autotab.xpi', 'temporary': True})
            extension_url = driver.script('''return WebExtensionPolicy.getByID(
                '{c2c003ee-bd69-42a2-b0e9-6f34222cb046}').getURL('data/options/index.html');''', True)
            driver.navigate(extension_url)
            result['extension_configure'] = driver.script('''let done=arguments[0];
              browser.storage.local.set({period:1,number:0,form:true,audio:true,
                favicon:false,prepends:'', 'startup-unpinned':false})
              .then(()=>done(true),e=>done({error:String(e)}));''', async_=True)
            driver.navigate('about:home')
        result['phases']['start'] = samples(driver.pid, sample_seconds)
        keys = sorted(set(PROJECT) | set(prefs) | {
            'image.mem.surfacecache.size_factor', 'image.mem.surfacecache.max_size_kb',
            'browser.cache.memory.capacity', 'browser.low_commit_space_threshold_mb',
            'layout.frame_rate', 'dom.ipc.forkserver.enable', 'b8k.bench.autoconfig'})
        result['effective_prefs'] = driver.script(prefs_script(keys), True, args=[keys])
        result['runtime'] = driver.script('''
          let gfx= Cc['@mozilla.org/gfx/info;1'].getService(Ci.nsIGfxInfo);
          let sys=Cc['@mozilla.org/system-info;1'].getService(Ci.nsIPropertyBag2);
          return {fission:Services.appinfo.fissionAutostart,
            physical_memory:sys.getProperty('memsize'),
            windows:Services.wm.getEnumerator('navigator:browser').hasMoreElements(),
            calm_timer:typeof __b8kCalmTimer,
            gfx:gfx.getInfo(),policy_status:Services.policies.status,
            policies:Services.policies.getActivePolicies()};''', True)
        result['addons'] = driver.script('''let done=arguments[0];
          ChromeUtils.importESModule('resource://gre/modules/AddonManager.sys.mjs')
          .AddonManager.getAllAddons().then(a=>done(a.map(x=>({id:x.id,version:x.version,
          active:x.isActive,type:x.type}))));''', True, True)
        for i in range(3):
            if i:
                handle = driver.call('POST', '/window/new', {'type': 'tab'})['handle']
                driver.call('POST', '/window', {'handle': handle})
            url = f'http://127.0.0.{i+1}:{port}/article?tab={i}'
            result['load_seconds'].append(driver.navigate(url))
            time.sleep(1)
            if i == 0:
                result['phases']['one_tab'] = samples(driver.pid, sample_seconds)
        result['fixture'] = driver.script('''return {
          ready:window.__ready===true, images:document.images.length,
          decoded:[...document.images].filter(x=>x.complete&&x.naturalWidth>0).length,
          elements:document.getElementsByTagName('*').length,
          reduced:matchMedia('(prefers-reduced-motion:reduce)').matches,
          entries:performance.getEntriesByType('resource').map(x=>({name:x.name,
            transfer:x.transferSize,decoded:x.decodedBodySize}))};''')
        result['phases']['three_tabs'] = samples(driver.pid, sample_seconds)
        # rAF is independent of the fixture's script setting.
        before = snapshot(driver.pid)
        result['raf'] = driver.script('''let done=arguments[0],n=0,start=performance.now();
          function frame(now){n++;scrollTo(0,(now-start)*5);
          if(now-start<2000)requestAnimationFrame(frame);
          else done({frames:n,elapsed:now-start});}requestAnimationFrame(frame);''', async_=True)
        after = snapshot(driver.pid)
        result['animation_cpu_seconds'] = (after['totals'].get('ticks', 0) -
            before['totals'].get('ticks', 0)) / os.sysconf('SC_CLK_TCK')
        # Actual content unload versus an extension merely being installed.
        if spec.get('discard'):
            result['discard'] = driver.script('''let tabs=[...gBrowser.tabs];
              return tabs.map(t=>t===gBrowser.selectedTab?false:gBrowser.discardBrowser(t));''', True)
        if spec.get('extension_discard'):
            # Exercise ATD's own timer; its scheduler has a 60-second minimum.
            # A direct native discard would not test the installed extension.
            time.sleep(65)
        if spec.get('unload'):
            time.sleep(7)
        if spec.get('reader'):
            result['load_seconds'].append(driver.navigate(
                'about:reader?url=' + urllib.parse.quote(
                    f'http://127.0.0.3:{port}/article?tab=2', safe='')))
            time.sleep(2)
        if spec.get('discard') or spec.get('extension_discard') or spec.get('unload') or spec.get('reader'):
            result['phases']['after_action'] = samples(driver.pid, sample_seconds)
            result['tab_state'] = driver.script('''return [...gBrowser.tabs].map(t=>({
              selected:t===gBrowser.selectedTab,pending:t.hasAttribute('pending'),
              remote:t.linkedBrowser.remoteType}));''', True)
        result['back_test'] = {}
        result['back_test']['away'] = driver.navigate('about:blank')
        t = time.monotonic()
        driver.call('POST', '/back', {})
        result['back_test']['seconds'] = time.monotonic() - t
        result['phases']['after_back'] = samples(driver.pid, sample_seconds)
        result['phases']['idle'] = samples(driver.pid, 5)
        with LOCK:
            result['requests'] = list(REQUESTS)
        result['status'] = 'ok'
    except Exception as e:
        result['status'], result['error'] = 'error', str(e)
    finally:
        if driver:
            driver.close()
        shutil.rmtree(profile, ignore_errors=True)
        result['ended'] = time.time()
        (OUT / 'runs' / (run_id + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--variants', default='project')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--sample-seconds', type=float, default=2)
    args = parser.parse_args()
    for folder in ['logs', 'runs']:
        (OUT / folder).mkdir(exist_ok=True)
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    names = list(VARIANTS) if args.variants == 'all' else args.variants.split(',')
    unknown = set(names) - VARIANTS.keys()
    if unknown:
        raise ValueError(unknown)
    for repeat in range(args.repeats):
        # Reverse order on alternating passes; baseline is included each pass.
        for name in names if repeat % 2 == 0 else list(reversed(names)):
            result = run_one(name, repeat, server.server_port, args.sample_seconds)
            phase = result['phases'].get('three_tabs', [])
            pss = statistics.median(s['totals'].get('Pss', 0) for s in phase) / 1024 if phase else None
            print(json.dumps({'variant': name, 'repeat': repeat,
                  'status': result['status'], 'pss_mib': pss,
                  'error': result.get('error')}), flush=True)
    server.shutdown()


if __name__ == '__main__':
    main()
