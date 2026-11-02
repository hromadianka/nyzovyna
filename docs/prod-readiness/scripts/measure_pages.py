"""Per-page measurement (in-process Django test Client). One fresh process per (db, page) so ru_maxrss is per page.
Usage: measure_pages.py <db: nyz_load|nyz_small> <path> [runs=15]  (NYZ_DEBUG=0 for timings; query count via CaptureQueriesContext)
Prints one JSON line."""
import sys, os, json, time, statistics, resource, tracemalloc
import django
django.setup()
import psutil
from django.test import Client
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from django.core.cache import cache

path = sys.argv[2]; runs = int(sys.argv[3]) if len(sys.argv) > 3 else 15
c = Client()
proc = psutil.Process()
c.get('/about-us')                      # warm imports/templates/connection (not the menu cache? it IS rendered here -> clear after)
cache.clear()
rss0 = proc.memory_info().rss
with CaptureQueriesContext(connection) as q0:
    t = time.perf_counter(); r = c.get(path); cold = time.perf_counter() - t
cold_q = len(q0)
times, nq, size = [], None, None
for _ in range(runs):
    with CaptureQueriesContext(connection) as q:
        t = time.perf_counter(); r = c.get(path); times.append(time.perf_counter() - t)
    nq = len(q); size = len(r.content)
    qtime = sum(float(x['time']) for x in q.captured_queries)
rss1 = proc.memory_info().rss
tracemalloc.start(); c.get(path); tm = tracemalloc.get_traced_memory()[1]; tracemalloc.stop()
times.sort()
p95 = times[min(len(times) - 1, int(round(0.95 * (len(times) - 1))))]
import app.models as _m
print(json.dumps(dict(db=sys.argv[1], src=_m.__file__, path=path, status=r.status_code, cold_ms=round(cold * 1000, 1), cold_q=cold_q,
    med_ms=round(statistics.median(times) * 1000, 1), p95_ms=round(p95 * 1000, 1), sql_q=nq, sql_ms=round(qtime * 1000, 1),
    html_kb=round(size / 1024, 1), rss_before_mb=round(rss0 / 2**20), rss_after_mb=round(rss1 / 2**20),
    maxrss_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20), tracemalloc_peak_mb=round(tm / 2**20, 1))))
