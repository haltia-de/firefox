#!/usr/bin/env python3
"""Software playback probe. Synthetic 360p30 clips, not a codec-quality benchmark."""
import http.server
import json
import os
from pathlib import Path
import shutil
import threading
import time
import urllib.parse
import run_matrix as m


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith('/video-'):
            file = m.OUT/'fixtures'/path[1:]
            body = file.read_bytes()
            mime = 'video/mp4' if file.suffix == '.mp4' else 'video/webm'
        else:
            codec = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('codec',['h264'])[0]
            ext = 'mp4' if codec == 'h264' else 'webm'
            body = (f'<html><body><button id="play" onclick="document.querySelector(\'video\').play()">Play</button>'
                f'<video width="640" height="360" muted loop controls src="/video-{codec}.{ext}"></video></body></html>').encode()
            mime = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


def state(d):
    return d.script('''let v=document.querySelector('video'),q=v.getVideoPlaybackQuality();
      return {paused:v.paused,time:v.currentTime,ready:v.readyState,width:v.videoWidth,
        height:v.videoHeight,total:q.totalVideoFrames,dropped:q.droppedVideoFrames,
        error:v.error?{code:v.error.code,message:v.error.message}:null};''')


out = m.OUT/'video'
out.mkdir(exist_ok=True)
server = http.server.ThreadingHTTPServer(('0.0.0.0',0), Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
for repeat in range(3):
    for codec in ['h264','vp9','av1'] if repeat%2==0 else ['av1','vp9','h264']:
        profile=Path('/home/bench/lab')/f'video-{codec}-{repeat}'
        shutil.rmtree(profile,ignore_errors=True);profile.mkdir()
        r={'codec':codec,'repeat':repeat,'started':time.time()};d=None
        try:
            prefs=m.configure('project',profile)
            d=m.Driver(profile,prefs,out/f'{codec}-{repeat}.log')
            d.navigate(f'http://127.0.0.1:{server.server_port}/?codec={codec}')
            r['autoplay']=d.script('''let done=arguments[0];document.querySelector('video').play()
              .then(()=>done({allowed:true}),e=>done({allowed:false,error:e.name}));''',async_=True)
            element=d.call('POST','/element',{'using':'css selector','value':'#play'})
            element_id=element['element-6066-11e4-a52e-4f735466cecf']
            d.call('POST','/element/'+element_id+'/click',{})
            time.sleep(1)
            a=m.snapshot(d.pid);r['before']=state(d)
            time.sleep(4)
            b=m.snapshot(d.pid);r['after']=state(d)
            r['cpu_s']=(b['totals'].get('ticks',0)-a['totals'].get('ticks',0))/os.sysconf('SC_CLK_TCK')
            r['pss_mib']=b['totals'].get('Pss',0)/1024
            r['status']='ok' if r['after']['width']==640 and r['after']['total']>r['before']['total'] else 'failed_playback'
        except Exception as e:
            r.update(status='error',error=str(e))
        finally:
            if d:d.close()
            shutil.rmtree(profile,ignore_errors=True)
            r['ended']=time.time()
            (out/f'{codec}-{repeat}.json').write_text(json.dumps(r,indent=2)+'\n')
        print(json.dumps({'codec':codec,'repeat':repeat,'status':r['status'],'cpu_s':r.get('cpu_s'),'error':r.get('error')}),flush=True)
server.shutdown()
