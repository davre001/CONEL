"""Standalone monitoring and repair worker: python -m backend.worker."""
import logging
import json
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def health_server(port, stopped, progress=None, ready=None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            initialized = ready is None or ready.is_set()
            healthy = (self.path == '/' or self.path == '/health' and initialized) and not stopped.is_set()
            self.send_response(200 if healthy else 503)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            payload = {'service': 'CONEL worker', 'process_ready': initialized,
                       'iterations': dict(progress or {})} if healthy else {}
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(('0.0.0.0', port), Handler)


def run_loop(action, delay, stopped, on_success=None):
    while not stopped.is_set():
        try:
            action()
            if on_success:
                on_success()
        except Exception:
            # Provider exceptions may contain credentials; do not log raw errors.
            logging.getLogger(__name__).warning('CONEL worker iteration failed; retrying')
        stopped.wait(delay)


def main():
    logging.basicConfig(level=logging.INFO)
    logging.info('CONEL standalone worker initializing')
    stopped = threading.Event()
    ready = threading.Event()
    progress = {'monitor': 0, 'repair': 0}
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    server = None
    if os.getenv('CONEL_WORKER_HEALTH_PORT'):
        server = health_server(int(os.environ['CONEL_WORKER_HEALTH_PORT']), stopped, progress, ready)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    from backend.config import Settings
    from backend.store import Store
    from backend.github_auth import GitHubAuth
    from backend.recovery import Recovery
    from backend.conel_repairs import RepairWorker

    settings = Settings.load()
    store = Store(settings.database)
    if not store.database.postgres:
        raise ValueError('Standalone worker requires PostgreSQL shared with the API')
    store.initialize()
    auth = GitHubAuth(store)
    auth.initialize()
    recovery = Recovery(store)
    worker = RepairWorker(recovery, auth)
    def completed(name):
        progress[name] += 1
        if progress[name] == 1:
            logging.info('CONEL worker %s loop completed its first iteration', name)
    ready.set()
    threads = [threading.Thread(target=run_loop, args=(action, delay, stopped,
                lambda name=name: completed(name)))
               for name, action, delay in (('monitor', recovery.tick, 5), ('repair', worker.once, 3))]
    for thread in threads:
        thread.start()
    logging.info('CONEL standalone worker started')
    # Finish in-flight work and its sandbox cleanup before exiting.
    for thread in threads:
        thread.join()
    if server:
        server.shutdown()
        server.server_close()
    logging.info('CONEL standalone worker stopped')


if __name__ == '__main__':
    main()
