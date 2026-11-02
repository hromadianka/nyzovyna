"""Deterministic AST mutation run (mutmut 3 needs a pytest harness; see REPORT.md).

usage: mutate.py <project_dir> <green_tests.txt> <out.json> [max_mutants] [workers]
A mutant is killed when any test that is green on the unmodified code fails (or errors) on the mutant.
"""
import ast
import concurrent.futures as cf
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

PY = os.environ.get('NYZ_PY', '/opt/homebrew/Caskroom/miniconda/base/envs/nyz-py313/bin/python')
TARGETS = ['app/views.py', 'app/models.py', 'app/context_processors.py']
SWAP_CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
            ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}


def offsets(src):
    starts, pos = [], 0
    for line in src.splitlines(keepends=True):
        starts.append(pos)
        pos += len(line.encode('utf-8'))
    return starts


def find_mutants(path, src):
    tree = ast.parse(src)
    raw = src.encode('utf-8')
    starts = offsets(src)
    lines = src.splitlines()
    out = []

    def span(node):
        return starts[node.lineno - 1] + node.col_offset, starts[node.end_lineno - 1] + node.end_col_offset

    def add(node, new, kind):
        a, b = span(node)
        out.append({'file': path, 'line': node.lineno, 'kind': kind, 'a': a, 'b': b, 'new': new,
                    'old': raw[a:b].decode('utf-8')[:60]})

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in SWAP_CMP:
            seg = raw[span(node.left)[1]:span(node.comparators[0])[0]].decode('utf-8')
            sym = {ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.GtE: '>=', ast.Gt: '>', ast.LtE: '<=',
                   ast.In: 'in', ast.NotIn: 'not in', ast.Is: 'is', ast.IsNot: 'is not'}
            new_sym = sym[SWAP_CMP[type(node.ops[0])]]
            old_sym = sym[type(node.ops[0])]
            if old_sym in seg:
                a = span(node.left)[1] + seg.index(old_sym)
                out.append({'file': path, 'line': node.lineno, 'kind': 'compare', 'a': a,
                            'b': a + len(old_sym.encode()), 'new': new_sym, 'old': old_sym})
        elif isinstance(node, ast.BoolOp) and len(node.values) == 2:
            seg = raw[span(node.values[0])[1]:span(node.values[1])[0]].decode('utf-8')
            old = 'and' if isinstance(node.op, ast.And) else 'or'
            if old in seg:
                a = span(node.values[0])[1] + seg.index(old)
                out.append({'file': path, 'line': node.lineno, 'kind': 'boolop', 'a': a, 'b': a + len(old),
                            'new': 'or' if old == 'and' else 'and', 'old': old})
        elif isinstance(node, ast.Constant):
            if node.value is True:
                add(node, 'False', 'bool')
            elif node.value is False:
                add(node, 'True', 'bool')
            elif isinstance(node.value, int) and not isinstance(node.value, bool) and node.value not in (0,):
                add(node, str(node.value + 1), 'int')
            elif isinstance(node.value, int) and not isinstance(node.value, bool):
                add(node, '1', 'int')
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            add(node, raw[span(node.operand)[0]:span(node.operand)[1]].decode('utf-8'), 'not')
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            add(node.value, 'None', 'return')
        elif isinstance(node, ast.Attribute) and node.attr in ('exclude', 'prefetch_related', 'select_related'):
            pass
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
            seg = raw[span(node.left)[1]:span(node.right)[0]].decode('utf-8')
            old = '+' if isinstance(node.op, ast.Add) else '-'
            if old in seg:
                a = span(node.left)[1] + seg.index(old)
                out.append({'file': path, 'line': node.lineno, 'kind': 'arith', 'a': a, 'b': a + 1,
                            'new': '-' if old == '+' else '+', 'old': old})
    return out


def apply(src, m):
    raw = src.encode('utf-8')
    return (raw[:m['a']] + m['new'].encode('utf-8') + raw[m['b']:]).decode('utf-8')


def run_one(args):
    project, tests, m = args
    work = tempfile.mkdtemp(prefix='mut_')
    try:
        for item in ['app', 'anarchia', 'templates', 'static', 'locale', 'media', 'manage.py']:
            src = os.path.join(project, item)
            dst = os.path.join(work, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy(src, dst)
        target = os.path.join(work, m['file'])
        with open(target, encoding='utf-8') as fh:
            original = fh.read()
        if m['kind'] != 'control':
            with open(target, 'w', encoding='utf-8') as fh:
                fh.write(apply(original, m))
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='anarchia.settings_test', PYTHONDONTWRITEBYTECODE='1')
        env.pop('NYZ_DB', None)
        try:
            done = subprocess.run([PY, 'manage.py', 'test', '--failfast', '--noinput', *tests], cwd=work, env=env,
                                  capture_output=True, text=True, timeout=240)
            status = 'survived' if done.returncode == 0 else 'killed'
            tail = '' if status == 'killed' else done.stderr[-120:]
        except subprocess.TimeoutExpired:
            status, tail = 'timeout', ''
        return dict(m, status=status, tail=tail)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    project, green, out = sys.argv[1:4]
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 150
    workers = int(sys.argv[5]) if len(sys.argv) > 5 else 6
    tests = [line.strip() for line in open(green) if line.strip()]
    mutants = []
    for rel in TARGETS:
        with open(os.path.join(project, rel), encoding='utf-8-sig') as fh:
            mutants += find_mutants(rel, fh.read())
    random.seed(42)
    random.shuffle(mutants)
    mutants = sorted(mutants[:limit], key=lambda m: (m['file'], m['line']))
    control = run_one((project, tests, {'file': TARGETS[0], 'line': 0, 'kind': 'control', 'a': 0, 'b': 0, 'new': '',
                                          'old': ''}))
    if control['status'] != 'survived':
        sys.exit(f'control run (no mutation) failed: {control}')
    with cf.ProcessPoolExecutor(workers) as pool:
        results = list(pool.map(run_one, [(project, tests, m) for m in mutants]))
    json.dump(results, open(out, 'w'), ensure_ascii=False, indent=1)
    from collections import Counter
    print(Counter(r['status'] for r in results))


if __name__ == '__main__':
    main()
