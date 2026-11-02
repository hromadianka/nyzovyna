release: python manage.py migrate --noinput
web: gunicorn anarchia.wsgi --workers ${WEB_CONCURRENCY:-2} --threads 2 --timeout 30 --worker-tmp-dir /dev/shm --max-requests 1000 --max-requests-jitter 100 --access-logfile -
