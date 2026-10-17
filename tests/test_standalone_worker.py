import threading

from backend.worker import run_loop


def test_worker_shutdown_finishes_current_action():
    stopped = threading.Event()
    calls = []
    def action():
        calls.append('started')
        stopped.set()
        calls.append('finished')
    run_loop(action, 30, stopped)
    assert calls == ['started', 'finished']


def test_worker_retries_without_logging_provider_secret(caplog):
    stopped = threading.Event()
    calls = []
    def action():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError('private-provider-token')
        stopped.set()
    run_loop(action, 0, stopped)
    assert len(calls) == 2
    assert 'private-provider-token' not in caplog.text
    assert 'iteration failed' in caplog.text


def test_health_supports_platform_root_probe_and_reports_progress():
    import json
    from urllib.request import urlopen
    from urllib.error import HTTPError
    import pytest
    from backend.worker import health_server
    stopped = threading.Event()
    server = health_server(0, stopped, {'monitor': 2, 'repair': 3})
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = 'http://127.0.0.1:'+str(server.server_port)
        for path in ('/', '/health'):
            with urlopen(base+path, timeout=2) as response:
                assert json.load(response)['iterations'] == {'monitor': 2, 'repair': 3}
        stopped.set()
        with pytest.raises(HTTPError) as failure:
            urlopen(base+'/health', timeout=2)
        assert failure.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_loop_progress_only_counts_successful_iterations():
    stopped = threading.Event()
    count = []
    def action():
        stopped.set()
    run_loop(action, 0, stopped, lambda: count.append(1))
    assert count == [1]
    stopped.clear()
    def failing():
        stopped.set()
        raise RuntimeError('controlled')
    run_loop(failing, 0, stopped, lambda: count.append(2))
    assert count == [1]


def test_liveness_precedes_database_readiness():
    import json
    from urllib.request import urlopen
    from urllib.error import HTTPError
    import pytest
    from backend.worker import health_server
    stopped, ready = threading.Event(), threading.Event()
    server = health_server(0, stopped, ready=ready)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        base = 'http://127.0.0.1:'+str(server.server_port)
        with urlopen(base+'/', timeout=2) as response:
            assert json.load(response)['process_ready'] is False
        with pytest.raises(HTTPError) as failure:
            urlopen(base+'/health', timeout=2)
        assert failure.value.code == 503
        ready.set()
        with urlopen(base+'/health', timeout=2) as response:
            assert json.load(response)['process_ready'] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
