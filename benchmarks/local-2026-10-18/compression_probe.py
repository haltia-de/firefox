#!/usr/bin/env python3
"""Userspace codec comparison on synthetic 4KiB pages; not a zram benchmark."""
import ctypes
import ctypes.util
import json
from pathlib import Path
import random
import statistics
import time

lz = ctypes.CDLL(ctypes.util.find_library('lz4'))
zs = ctypes.CDLL(ctypes.util.find_library('zstd'))
lz.LZ4_compressBound.argtypes = [ctypes.c_int]
lz.LZ4_compressBound.restype = ctypes.c_int
lz.LZ4_compress_default.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
lz.LZ4_compress_default.restype = ctypes.c_int
zs.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
zs.ZSTD_compressBound.restype = ctypes.c_size_t
zs.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
zs.ZSTD_compress.restype = ctypes.c_size_t
rng = random.Random(20261018)
size = 2 * 1024 * 1024
phrase = b'Firefox browser article deterministic text memory corpus. '
text = (phrase * (size // len(phrase) + 1))[:size]
heap = bytearray(size)
for i in range(0, size, 4096):
    heap[i] = (i // 4096) % 256
payloads = {'repeated_text': text, 'random_pixels': rng.randbytes(size),
            'sparse_heap': bytes(heap)}
results = []
for corpus, data in payloads.items():
    pages = [ctypes.create_string_buffer(data[i:i+4096]) for i in range(0, size, 4096)]
    for codec in ['lz4', 'zstd1', 'zstd3']:
        bound = lz.LZ4_compressBound(4096) if codec == 'lz4' else zs.ZSTD_compressBound(4096)
        dest = ctypes.create_string_buffer(bound)
        durations = []
        for _ in range(7):
            total = 0
            start = time.perf_counter()
            for src in pages:
                n = lz.LZ4_compress_default(src, dest, 4096, bound) if codec == 'lz4' else zs.ZSTD_compress(dest, bound, src, 4096, int(codec[-1]))
                assert 0 < n <= bound
                total += n
            durations.append((time.perf_counter() - start) * 1000)
        results.append({'corpus': corpus, 'codec': codec, 'page_bytes': 4096,
            'input_bytes': size, 'output_bytes': total, 'ratio': size / total,
            'median_ms': statistics.median(durations), 'min_ms': min(durations),
            'max_ms': max(durations),
            'scope': 'synthetic x86_64 userspace pages; Python/FFI overhead; no zram allocator, Firefox heap or ARM timing'})
out = Path(__file__).parent / 'compression-pages.json'
out.write_text(json.dumps(results, indent=2) + '\n')
for result in results:
    print(result['corpus'], result['codec'], round(result['ratio'], 2), round(result['median_ms'], 2))
