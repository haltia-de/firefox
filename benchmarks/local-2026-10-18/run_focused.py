#!/usr/bin/env python3
"""Repeat the memory comparisons and exercise decoder/JIT mechanisms separately."""
import argparse
import http.server
import json
import os
from pathlib import Path
import shutil
import statistics
import threading
import time
import run_matrix as m


def main():
    args = argparse.ArgumentParser()
    args.add_argument('--variants', default='project,no_images,disk_cache_off,native_discard,frame_rate30')
    args.add_argument('--repeats', type=int, default=4)
    args.add_argument('--suite', choices=['memory', 'image-stress', 'cpu'], default='memory')
    opt = args.parse_args()
    out = m.OUT / ('focused-' + opt.suite)
    out.mkdir(exist_ok=True)
    server = http.server.ThreadingHTTPServer(('0.0.0.0', 0), m.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    variants = opt.variants.split(',')
    for repeat in range(opt.repeats):
        for name in variants if repeat % 2 == 0 else list(reversed(variants)):
            profile = Path('/home/bench/lab') / f'focused-{opt.suite}-{name}-{repeat}'
            shutil.rmtree(profile, ignore_errors=True)
            profile.mkdir()
            r = {'variant': name, 'repeat': repeat, 'suite': opt.suite, 'phases': {}, 'started': time.time()}
            d = None
            try:
                prefs = m.configure(name, profile)
                d = m.Driver(profile, prefs, out / f'{name}-{repeat}.log')
                r['capabilities'] = d.caps
                d.navigate('about:home')
                time.sleep(2)
                r['start'] = m.samples(d.pid, 1)
                if opt.suite == 'cpu':
                    d.navigate('about:buildconfig')
                    r['buildconfig'] = d.script('return document.body.innerText;')
                    d.navigate(f'http://127.0.0.1:{server.server_port}/article')
                    r['javascript'] = []
                    for _ in range(6):
                        r['javascript'].append(d.script('''let s=performance.now(),x=0;
                          for(let i=0;i<5000000;i++)x+=(i%997)*Math.sqrt(i%1234);
                          return {ms:performance.now()-s,checksum:x};'''))
                    r['gfx'] = d.script('''let g=Cc['@mozilla.org/gfx/info;1'].getService(Ci.nsIGfxInfo);
                      try {return {features:g.getFeatures(), featureLog:g.getFeatureLog()};}
                      catch(e){return {error:String(e)};}''', True)
                else:
                    first_handle = d.call('GET', '/window')
                    for i in range(3):
                        if i:
                            d.call('POST', '/moz/context', {'context': 'content'})
                            handle = d.call('POST', '/window/new', {'type': 'tab'})['handle']
                            d.call('POST', '/window', {'handle': handle})
                        d.navigate(f'http://127.0.0.{i+1}:{server.server_port}/article?tab={i}')
                        if opt.suite == 'image-stress':
                            r.setdefault('decode', []).append(d.script('''let done=arguments[0];
                              Promise.allSettled([...document.images].map(i=>i.decode()))
                              .then(a=>done(a.map(x=>x.status)));''', async_=True))
                        time.sleep(1)
                    r['phases']['three_tabs'] = m.samples(d.pid, 1)
                    before = m.snapshot(d.pid)
                    r['raf'] = d.script('''let done=arguments[0],n=0,s=performance.now();
                      function f(t){n++;scrollTo(0,(t-s)*5);if(t-s<2000)requestAnimationFrame(f);
                      else done({frames:n,elapsed:t-s});}requestAnimationFrame(f);''', async_=True)
                    after = m.snapshot(d.pid)
                    r['animation_cpu_seconds'] = (after['totals'].get('ticks',0) - before['totals'].get('ticks',0))/os.sysconf('SC_CLK_TCK')
                    if name == 'native_discard':
                        r['discard'] = d.script('''return [...gBrowser.tabs].map(t=>
                          t===gBrowser.selectedTab?false:gBrowser.discardBrowser(t));''', True)
                    # Same settling time with and without discard. Pending is
                    # not evidence that allocators already returned memory.
                    time.sleep(7)
                    r['phases']['after_action'] = m.samples(d.pid, 1)
                    if name == 'native_discard':
                        d.call('POST', '/moz/context', {'context': 'content'})
                        d.call('POST', '/window', {'handle': first_handle})
                        time.sleep(1)
                        r['restored_tab'] = d.script('''return {ready:window.__ready===true,
                          images:document.images.length,url:location.href};''')
                r['status'] = 'ok'
            except Exception as e:
                r.update(status='error', error=str(e))
            finally:
                if d:
                    d.close()
                shutil.rmtree(profile, ignore_errors=True)
                r['ended'] = time.time()
                (out / f'{name}-{repeat}.json').write_text(json.dumps(r, indent=2)+'\n')
            print(json.dumps({'suite': opt.suite, 'variant':name,'repeat':repeat,'status':r['status'],
                              'error':r.get('error')}), flush=True)
    server.shutdown()


if __name__ == '__main__':
    main()
