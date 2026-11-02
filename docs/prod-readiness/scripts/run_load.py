"""Start gunicorn (anarchia.wsgi, like the Procfile) with N workers on 127.0.0.1:<port>, drive with locust headless,
sample RSS of master+workers every 15 s. Usage:
 run_load.py --workers 4 --debug 1 --users 20 --time 90 --port 8125 --tag w4_debug1 [--db nyz_load] [--threads 1]"""
import argparse, subprocess, os, time, json, csv, signal, psutil, sys
ap = argparse.ArgumentParser()
ap.add_argument('--workers', type=int, default=1); ap.add_argument('--debug', default='1'); ap.add_argument('--users', type=int, default=20)
ap.add_argument('--time', type=int, default=90); ap.add_argument('--port', type=int, default=8125); ap.add_argument('--tag', required=True)
ap.add_argument('--db', default='nyz_load'); ap.add_argument('--out', default='.'); ap.add_argument('--sample', type=int, default=15)
a = ap.parse_args()
R = os.environ.get('NYZ_SRC', '/Users/d/Development/Projects/nyz'); SC = '/Users/d/Development/Projects/nyz/docs/prod-readiness/scripts'; PYB = '/opt/homebrew/Caskroom/miniconda/base/envs/nyz/bin'
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=f'{R}:{SC}',
           DJANGO_SETTINGS_MODULE='nyz_load_settings', NYZ_LOAD_DB=a.db, NYZ_DEBUG=a.debug)
g = subprocess.Popen([f'{PYB}/gunicorn', 'anarchia.wsgi', '-w', str(a.workers), '-b', f'127.0.0.1:{a.port}', '--log-level', 'warning'],
                     cwd=R, env=env, stdout=open(f'{a.out}/{a.tag}_gunicorn.log', 'w'), stderr=subprocess.STDOUT)
for _ in range(60):   # wait until listening
    try:
        import urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{a.port}/about-us', timeout=5).read(); break
    except Exception: time.sleep(0.5)
rss_log = open(f'{a.out}/{a.tag}_rss.csv', 'w'); rss_log.write('t_s,master_mb,workers_mb\n')
L = subprocess.Popen([f'{PYB}/locust', '-f', f'{SC}/locustfile.py', '--headless', '-u', str(a.users), '-r', str(a.users),
                      '-t', f'{a.time}s', '--host', f'http://127.0.0.1:{a.port}', '--csv', f'{a.out}/{a.tag}', '--only-summary'],
                     env=env, stdout=open(f'{a.out}/{a.tag}_locust.log', 'w'), stderr=subprocess.STDOUT)
t0 = time.time(); m = psutil.Process(g.pid)
while L.poll() is None:
    try:
        ws = [round(c.memory_info().rss / 2**20, 1) for c in m.children()]
        rss_log.write(f'{int(time.time()-t0)},{round(m.memory_info().rss/2**20,1)},{" ".join(map(str, ws))}\n'); rss_log.flush()
    except psutil.Error: pass
    time.sleep(a.sample)
g.send_signal(signal.SIGTERM)
try: g.wait(20)
except Exception: g.kill()
rows = list(csv.DictReader(open(f'{a.out}/{a.tag}_stats.csv')))
for r in rows:
    print(a.tag, r['Name'], 'n=', r['Request Count'], 'fail=', r['Failure Count'], 'rps=', round(float(r['Requests/s']), 1),
          'p50=', r['50%'], 'p95=', r['95%'], 'p99=', r['99%'], 'avg=', round(float(r['Average Response Time'])), 'avgKB=', round(float(r['Average Content Size']) / 1024, 1))
