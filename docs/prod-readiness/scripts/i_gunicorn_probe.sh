#!/bin/bash
# Usage: i_gunicorn_probe.sh <workers> <debug 0|1> [extra gunicorn args]
# Needs env.sh in scratchpad (PY, PYTHONPATH with wrap_settings, DJANGO_SETTINGS_MODULE=wrap_settings), migrated SQLite and collectstatic'd STATIC_ROOT.
W=$1; D=$2; shift 2
GU=$(dirname $PY)/gunicorn
WRAP_DEBUG=$D WRAP_ALLOWED=127.0.0.1,localhost $GU anarchia.wsgi -b 127.0.0.1:8123 -w $W "$@" > ${NYZ_SCR}/gunicorn_w${W}_d${D}.log 2>&1 &
GP=$!
for i in $(seq 1 40); do /usr/bin/curl -s -o /dev/null http://127.0.0.1:8123/static/style.css && break; sleep 0.25; done
B=http://127.0.0.1:8123
probe() { echo "### $1 $2"; /usr/bin/curl -s -D - -o /dev/null $3 "$B$1" | /usr/bin/awk 'NR==1 || tolower($0) ~ /^(content-type|cache-control|content-encoding|vary|content-length|x-frame|x-content|referrer|cross-origin|strict-transport|content-language|set-cookie|location|etag|last-modified|server|x-)/' | /usr/bin/tr -d '\r'; }
CSS=$(ls ${NYZ_SCR}/static_out | /usr/bin/grep -E '^style\.[0-9a-f]+\.css$' | head -1)
probe / ""
probe /static/style.css ""
probe /static/style.css "gzip" "-H Accept-Encoding:gzip"
probe /static/$CSS "hashed gzip" "-H Accept-Encoding:gzip"
probe /static/img/bg.png "unhashed png"
probe /media/test.txt ""
probe /robots.txt ""
probe /healthz ""
probe /no-such-page ""
probe /about-us "(500 expected on empty DB)"
probe /static/missing.css ""
probe /article/does-not-exist/ ""
echo "### HEAD / X-Forwarded-Proto https"; /usr/bin/curl -s -I -H 'X-Forwarded-Proto: https' $B/ | /usr/bin/tr -d '\r' | head -20
kill $GP; wait $GP 2>/dev/null
