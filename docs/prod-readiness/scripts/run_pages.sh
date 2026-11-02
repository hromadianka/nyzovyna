#!/bin/bash
# usage: run_pages.sh <db> <leaf-slug>  -> JSON lines
DB=$1; LEAF=$2; R=/Users/d/Development/Projects/nyz; SRC=${NYZ_SRC:-$R}
PY=/opt/homebrew/Caskroom/miniconda/base/envs/nyz/bin/python
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$SRC:$R/docs/prod-readiness/scripts DJANGO_SETTINGS_MODULE=nyz_load_settings NYZ_LOAD_DB=$DB NYZ_DEBUG=${NYZ_DEBUG:-0}
for P in / /all /category/cat-r-00/ /category/$LEAF/ /article/article-c5/ /article/article-cbig/ /authors /authors/author-heavy \
  "/search/?q=%D0%BA%D0%B2%D0%B0%D0%B7%D1%96%D0%BF%D1%83%D0%BB%D1%8C%D1%81%D0%B0%D1%80" "/search/?q=%D1%81%D1%82%D0%B0%D1%82%D1%82%D1%8F" "/search/?q=zzzxxx" "/search/?q=" /feed/ /sitemap.xml /about-us; do
  $PY $R/docs/prod-readiness/scripts/measure_pages.py $DB "$P" ${RUNS:-15} 2>&1 | grep '^{' || echo "FAIL $P"
done
