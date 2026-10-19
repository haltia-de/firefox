#!/usr/bin/env python3
"""Generate the local corpus. Requires Pillow; videos also need host ffmpeg."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument('--videos', action='store_true')
args = parser.parse_args()
root = Path(__file__).parent / 'fixtures'
root.mkdir(exist_ok=True)
if args.videos:
    specs = {'h264': ('libx264', ['-preset', 'veryfast', '-crf', '28'], 'mp4'),
             'vp9': ('libvpx-vp9', ['-deadline', 'realtime', '-cpu-used', '8', '-crf', '36', '-b:v', '0'], 'webm'),
             'av1': ('libaom-av1', ['-cpu-used', '8', '-crf', '40', '-b:v', '0'], 'webm')}
    for name, (codec, options, ext) in specs.items():
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi',
            '-i', 'testsrc2=size=640x360:rate=30', '-t', '8', '-an', '-c:v', codec,
            '-threads', '1', *options, str(root / f'video-{name}.{ext}')], check=True)
else:
    rng = random.Random(20261018)
    for i in range(16):
        img = Image.frombytes('RGB', (1200, 900), rng.randbytes(1200*900*3))
        img.save(root / f'image-{i:02d}.jpg', quality=60)
manifest = {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(root.iterdir()) if p.name != 'manifest.json'}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
