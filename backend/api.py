"""CONEL authenticated application-monitoring and recovery API."""
import asyncio
from contextlib import asynccontextmanager
import logging
import os
from urllib.parse import urlparse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import Settings
from backend.github_auth import GitHubAuth
from backend.public_boundary import PublicBoundary, PublicPolicy
from backend.recovery import Recovery, routes as recovery_routes
from backend.store import Store


def create_app(settings=None):
    settings = settings or Settings.load()
    store = Store(settings.database)
    auth = GitHubAuth(store)
    recovery = Recovery(store)
    policy = PublicPolicy.load(auth)

    @asynccontextmanager
    async def lifespan(app):
        recovery.initialize()
        auth.initialize()

        async def repeat(action, delay):
            while True:
                try:
                    await asyncio.to_thread(action)
                except Exception:
                    logging.getLogger(__name__).warning('CONEL background iteration failed; retrying')
                await asyncio.sleep(delay)

        tasks = []
        if os.getenv('CONEL_BACKGROUND_ENABLED', '1') == '1':
            tasks = [asyncio.create_task(repeat(recovery.tick, 5)),
                     asyncio.create_task(repeat(app.state.repair_worker.once, 3))]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title='CONEL backend', lifespan=lifespan)
    if policy:
        app.add_middleware(PublicBoundary, store=store, policy=policy)
        hosts = [policy.host]
        backend_origin = os.getenv('CONEL_BACKEND_ORIGIN', '')
        if backend_origin:
            parsed = urlparse(backend_origin)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment or parsed.path not in {'', '/'}
                    or not os.getenv('CONEL_PROXY_SECRET')):
                raise ValueError('Backend proxy requires an HTTPS origin and CONEL_PROXY_SECRET')
            hosts.append(parsed.hostname)
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts, www_redirect=False)
    app.add_middleware(CORSMiddleware, allow_origins=[auth.origin], allow_credentials=True,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type', 'X-CSRF-Token'])

    @app.middleware('http')
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    app.state.store = store
    app.state.settings = settings
    app.state.github_auth = auth
    auth.routes(app)
    recovery_routes(app, recovery, auth)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'service': 'CONEL'}

    return app


app = create_app()
