"""UniBarrageAPI 集成测试:用线程内 fake server 验证真实 HTTP 路径。"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from bilidm_overlay.api import UniBarrageAPI, UniBarrageError


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/all":
            self._send(200, {"code": 200, "message": "ok", "data": [
                {"platform": "bilibili", "rid": "1813444381"},
            ]})
        else:
            self._send(404, {"code": 404, "message": "not found"})

    def do_POST(self):
        if self.path == "/api/v1/bilibili":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            self._send(201, {"code": 201, "message": "ok", "data": body})
        else:
            self._send(400, {"code": 400, "message": "bad"})

    def do_DELETE(self):
        if self.path == "/api/v1/bilibili/1813444381":
            self._send(200, {"code": 200, "message": "ok"})
        else:
            self._send(404, {"code": 404, "message": "服务未找到"})


@pytest.fixture()
def server_url():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_list_all(server_url):
    api = UniBarrageAPI(server_url)
    services = api.list_all()
    assert services == [{"platform": "bilibili", "rid": "1813444381"}]


def test_start_sends_body(server_url):
    api = UniBarrageAPI(server_url)
    api.start("bilibili", "1813444381", cookie="abc")


def test_stop(server_url):
    api = UniBarrageAPI(server_url)
    api.stop("bilibili", "1813444381")


def test_stop_missing_raises(server_url):
    api = UniBarrageAPI(server_url)
    with pytest.raises(UniBarrageError) as exc:
        api.stop("bilibili", "999")
    assert exc.value.code == 404
