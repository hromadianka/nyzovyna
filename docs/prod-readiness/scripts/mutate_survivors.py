"""Re-test surviving mutants: (1) with the extended green set, (2) against the full suite, where a mutant counts as
detected by a currently-red test if it changes the set of failing tests compared with the unmutated baseline.

usage: mutate_survivors.py <project_dir> <green.txt> <mutants.json> <baseline_sqlite.log> <out.json> [workers]
"""
import concurrent.futures as cf
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import mutate  # noqa: E402


def failing_set(text):
    return set(re.findall(r'^(?:FAIL|ERROR): (\w+ \([\w.]+\)(?: \(.*\))?)$', text, re.M))


def run_full(args):
    project, m, baseline_red = args
    work = tempfile.mkdtemp(prefix='mutfull_')
    try:
        for item in ['app', 'anarchia', 'templates', 'static', 'locale', 'media', 'manage.py']:
            src, dst = os.path.join(project, item), os.path.join(work, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy(src, dst)
        target = os.path.join(work, m['file'])
        original = open(target, encoding='utf-8').read()
        open(target, 'w', encoding='utf-8').write(mutate.apply(original, m))
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='anarchia.settings_test', PYTHONDONTWRITEBYTECODE='1')
        env.pop('NYZ_DB', None)
        done = subprocess.run([mutate.PY, 'manage.py', 'test', 'prod_tests', 'app.test_findings', '-v', '2',
                               '--noinput'], cwd=work, env=env, capture_output=True, text=True, timeout=600)
        red = failing_set(done.stderr + done.stdout)
        new = sorted(red - baseline_red)
        gone = sorted(baseline_red - red)
        return dict(m, full_status='detected_by_red_tests' if (new or gone) else 'survived',
                    changed_tests=(new + gone)[:3])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    project, green, mutants_json, baseline_log, out = sys.argv[1:6]
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 6
    tests = [x.strip() for x in open(green) if x.strip()] + ['prod_tests.test_k_mutation']
    survivors = [m for m in json.load(open(mutants_json)) if m['status'] == 'survived']
    baseline_red = failing_set(open(baseline_log, encoding='utf-8', errors='replace').read())
    with cf.ProcessPoolExecutor(workers) as pool:
        pass1 = list(pool.map(mutate.run_one, [(project, tests, m) for m in survivors]))
    remaining = [m for m in pass1 if m['status'] == 'survived']
    with cf.ProcessPoolExecutor(workers) as pool:
        pass2 = list(pool.map(run_full, [(project, m, baseline_red) for m in remaining]))
    json.dump({'extended_green': pass1, 'full_suite': pass2}, open(out, 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    print('after new tests:', Counter(m['status'] for m in pass1))
    print('full suite on remaining:', Counter(m['full_status'] for m in pass2))


if __name__ == '__main__':
    main()
