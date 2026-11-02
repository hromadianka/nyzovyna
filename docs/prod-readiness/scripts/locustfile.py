"""Locust mix against local gunicorn (localhost only). Slugs match gen_data.py (large DB)."""
import random
from locust import HttpUser, task, between
random.seed(42)
ARTICLES = [f'article-{i:05d}' for i in range(0, 10000)]
LEAVES = [f'cat-l-{i:03d}' for i in range(0, 450)]
WORDS = ['стаття', 'квазіпульсар', 'місто', 'zzzxxx', 'історія', 'музика', 'вода', 'article', 'war']

class Reader(HttpUser):
    wait_time = between(0.05, 0.3)

    @task(35)
    def home(self): self.client.get('/', name='/')

    @task(35)
    def article(self):
        # 2% hit the 5000-comment article, as a heavy-tail probe
        slug = 'article-cbig' if random.random() < 0.02 else random.choice(ARTICLES)
        self.client.get(f'/article/{slug}/', name='/article/<slug>')

    @task(15)
    def category(self):
        slug = random.choice(['cat-r-00', 'cat-r-03', 'cat-m-05', 'cat-l-000']) if random.random() < .3 else random.choice(LEAVES)
        self.client.get(f'/category/{slug}/', name='/category/<slug>/')

    @task(10)
    def search(self): self.client.get('/search/', params={'q': random.choice(WORDS)}, name='/search/?q')

    @task(5)
    def all_(self): self.client.get('/all', name='/all')


class Light(HttpUser):
    """LOCUST_MIX=light: only home + article (the 'typical page' capacity probe)."""
    wait_time = between(0.05, 0.3)
    abstract = True

    @task(1)
    def home(self): self.client.get('/', name='/')

    @task(1)
    def article(self): self.client.get(f'/article/{random.choice(ARTICLES)}/', name='/article/<slug>')

import os as _os
if _os.environ.get('LOCUST_MIX') == 'light':
    Reader.abstract = True
    class LightUser(Light):
        abstract = False
