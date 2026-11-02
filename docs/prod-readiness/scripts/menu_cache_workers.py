"""D5: LocMemCache menu per worker. gunicorn -w 4 on :8127 against nyz_load (DEBUG=0). Needs an editor user (created here, removed at end).
1) cold vs warm per worker (access log with pid + request time)  2) create a category through the app (POST /create-category/, post_save
-> invalidate in the ONE worker that served it) and tally which pids still render the old menu, polled for --watch seconds."""
import os, re, subprocess, sys, time, signal, collections, statistics, json, argparse
import requests
ap = argparse.ArgumentParser(); ap.add_argument('--watch', type=int, default=300); ap.add_argument('--port', type=int, default=8127)
ap.add_argument('--out', required=True); a = ap.parse_args()
R = os.environ.get('NYZ_SRC', '/Users/d/Development/Projects/nyz'); SC = '/Users/d/Development/Projects/nyz/docs/prod-readiness/scripts'; PYB = '/opt/homebrew/Caskroom/miniconda/base/envs/nyz/bin'
env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=f'{R}:{SC}', DJANGO_SETTINGS_MODULE='nyz_load_settings',
           NYZ_LOAD_DB='nyz_load', NYZ_DEBUG=os.environ.get('D5_DEBUG','0'))
subprocess.run([f'{PYB}/python', '-c', "import django;django.setup();from django.contrib.auth.models import User;User.objects.filter(username='perf_editor').delete();User.objects.create_user('perf_editor',password='pw-perf-1')"], env=env, cwd=R, check=True, capture_output=True)
logf = f'{a.out}/d5_access.log'
t_start = time.time()
g = subprocess.Popen([f'{PYB}/gunicorn', 'anarchia.wsgi', '-w', '4', '-b', f'127.0.0.1:{a.port}', '--access-logfile', logf,
                      '--access-logformat', 'PID=%(p)s T=%(L)s S=%(s)s R=%(r)s', '--log-level', 'warning'], cwd=R, env=env)
base = f'http://127.0.0.1:{a.port}'
while True:
    try: requests.get(base + '/about-us', timeout=5); break
    except Exception: time.sleep(0.1)
boot = time.time() - t_start
print('gunicorn boot -> first 200 (s):', round(boot, 2))
def parse():
    out = []
    for l in open(logf):
        m = re.match(r'PID=<(\d+)> T=([\d.]+) S=(\d+) R=GET (\S+)', l)
        if m: out.append((int(m[1]), float(m[2]) * 1000, int(m[3]), m[4]))
    return out
# 1) cold/warm: fresh process-wide cache -> each worker's first '/' is cold
n0 = len(parse())
for i in range(120): requests.get(f'{base}/?n={i}')
rows = [r for r in parse()[n0:] if r[3].startswith('/?n=')]
per = collections.defaultdict(list)
for pid, ms, st, p in rows: per[pid].append(ms)
print('workers seen:', len(per))
for pid, v in per.items(): print(f'  pid {pid}: first(cold)={v[0]:.1f}ms, warm median={statistics.median(v[1:]):.1f}ms, n={len(v)}')
# 2) invalidation in a single worker
# settings.py has *_COOKIE_SECURE=True, so requests would not send the cookies over http: pass them by hand and pretend https via X-Forwarded-Proto
s = requests.Session(); H = {'X-Forwarded-Proto': 'https', 'Referer': base.replace('http', 'https') + '/'}
def ck(): return {'Cookie': '; '.join(f'{k}={v}' for k, v in s.cookies.get_dict().items())}
s.get(base + '/login/', headers=H); tok = s.cookies.get_dict()['csrftoken']
r = s.post(base + '/login/', data={'login': 'perf_editor', 'password': 'pw-perf-1', 'csrfmiddlewaretoken': tok}, headers={**H, **ck()}, allow_redirects=False)
print('login status', r.status_code)
# editor-cabinet needs AboutUs pk=1 (exists in nyz_load)
NEW = 'STALEPROBE%d' % int(time.time())
tok = s.cookies.get_dict()['csrftoken']
n1 = len(parse())
r = s.post(base + '/create-category/', data={'name_ua': NEW, 'name_en': NEW + 'en', 'csrfmiddlewaretoken': tok}, headers={**H, **ck()}, allow_redirects=False)
print('create-category status', r.status_code, r.text[:200].replace('\n',' ') if r.status_code==403 else '', 'at', time.strftime('%X'))
post_rows = [x for x in parse()[n1:]]
# the pid that served POST = pid on the POST line (our regexp only parses GET) -> re-parse raw
raw = [l for l in open(logf) if 'POST /create-category/' in l][-1]; wpid = int(re.search(r'PID=<(\d+)>', raw)[1]); print('writer pid', wpid)
tally = []
def poll(label, n):
    fresh, stale = collections.Counter(), collections.Counter()
    start = len(parse())
    rs = []
    for i in range(n):
        h = requests.get(f'{base}/?p={label}-{i}').text
        rs.append(NEW in h)
    got = parse()[start:]
    got = [g for g in got if g[3].startswith(f'/?p={label}-')]
    for (pid, ms, st, p), is_fresh in zip(got, rs): (fresh if is_fresh else stale)[pid] += 1
    return fresh, stale
t0 = time.time(); k = 0; log = []
while True:
    f, st = poll(f't{k}', 60)
    pids = sorted(set(f) | set(st))
    line = {'t_s': int(time.time() - t0), 'fresh_pids': sorted(f), 'stale_pids': sorted(st), 'mixed': sorted(set(f) & set(st))}
    print(json.dumps(line)); log.append(line)
    k += 1
    if time.time() - t0 > a.watch: break
    time.sleep(30)
# cleanup
s.get(base + '/category/' + 'x/')  # noop
g.send_signal(signal.SIGTERM); g.wait(20)
subprocess.run([f'{PYB}/python', '-c', f"import django;django.setup();from django.contrib.auth.models import User;from app.models import Category;User.objects.filter(username='perf_editor').delete();print('deleted cats',Category.objects.filter(name_ua='{NEW}').delete())"], env=env, cwd=R, capture_output=True)
json.dump(dict(writer=wpid, log=log, boot=boot), open(f'{a.out}/d5_result.json', 'w'))
