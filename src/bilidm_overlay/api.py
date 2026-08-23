"""UniBarrage HTTP API 客户端(房间管理:列表/添加/删除)。

本地 127.0.0.1 服务,同步 urllib 足够(毫秒级响应,不引入线程复杂度)。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"


def default_api_address() -> str:
    """优先读 dmnotifier 已配置的 server 段,回退本地默认。"""
    import yaml

    p = os.path.expanduser("~/.config/dmnotifier/config.yaml")
    try:
        data = yaml.safe_load(open(p, encoding="utf-8")) or {}
        return data.get("server", {}).get("api_address", BASE)
    except OSError:
        return BASE


def default_api_token() -> str:
    import yaml

    p = os.path.expanduser("~/.config/dmnotifier/config.yaml")
    try:
        data = yaml.safe_load(open(p, encoding="utf-8")) or {}
        return data.get("server", {}).get("api_token", "")
    except OSError:
        return ""


class UniBarrageAPI:
    def __init__(self, base: str = BASE, token: str = "") -> None:
        self._base = base.rstrip("/")
        self._token = token

    def _url(self, path: str) -> str:
        return f"{self._base}/api/v1/{path}"

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self._url(path), method=method)
        if self._token:
            req.add_header("Authorization", f"Bearer {self._token}")
        data = None
        if body is not None:
            req.add_header("Content-Type", "application/json")
            data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(req, data=data, timeout=3) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode())
            except (ValueError, TypeError):
                payload = {}
            raise UniBarrageError(e.code, payload.get("message", e.reason)) from e
        except urllib.error.URLError as e:
            raise UniBarrageError(0, f"无法连接 UniBarrage: {e.reason}") from e

    def list_all(self) -> list[dict]:
        """GET /api/v1/all → [{"platform","rid"}, ...]"""
        resp = self._request("GET", "all")
        if resp.get("code") != 200:
            raise UniBarrageError(resp.get("code", 0), resp.get("message", "未知错误"))
        return resp.get("data") or []

    def start(self, platform: str, rid: str, cookie: str = "") -> None:
        body: dict = {"rid": rid}
        if cookie:
            body["cookie"] = cookie
        resp = self._request("POST", platform, body)
        if resp.get("code") not in (200, 201):
            raise UniBarrageError(resp.get("code", 0), resp.get("message", "未知错误"))

    def stop(self, platform: str, rid: str) -> None:
        resp = self._request("DELETE", f"{platform}/{rid}")
        if resp.get("code") not in (200, 201):
            raise UniBarrageError(resp.get("code", 0), resp.get("message", "未知错误"))


class UniBarrageError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")
