#!/bin/sh
# usage: run_prod_tests.sh sqlite|mysql   -> writes summary and raw log to the given directory (default /tmp)
cd "$(dirname "$0")/../../.." || exit 1
OUT=${2:-/tmp}
if [ "$1" = mysql ]; then export NYZ_DB=mysql; fi
PYTHONDONTWRITEBYTECODE=1 DJANGO_SETTINGS_MODULE=anarchia.settings_test \
  /opt/homebrew/Caskroom/miniconda/base/envs/nyz/bin/python manage.py test prod_tests -v 2 > "$OUT/prod_$1.log" 2>&1
python3 - "$OUT/prod_$1.log" <<'PY'
import re, sys
log = open(sys.argv[1], encoding='utf-8', errors='replace').read()
ran = re.search(r'Ran (\d+) tests', log)
fails = set(re.findall(r'^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)', log, re.M))
subs = len(re.findall(r'^(?:FAIL|ERROR): \w+ \([\w.]+\) \(', log, re.M))
skipped = len(re.findall(r'skipped', log.split('Ran ')[-1]))
print('ran', ran.group(1) if ran else '?', '| failing test methods', len(fails), '| failing subtests', subs, '|', log.strip().splitlines()[-2:])
PY
