"""AvatarCache 纯逻辑测试:缓存路径与磁盘命中。"""

import os
import tempfile

from bilidm_overlay.danmaku.avatars import avatar_cache_path


def test_cache_path_deterministic_and_unique():
    p1 = avatar_cache_path("https://x/a.png", "/tmp/cache-avatars/")
    p2 = avatar_cache_path("https://x/a.png", "/tmp/cache-avatars/")
    p3 = avatar_cache_path("https://x/b.png", "/tmp/cache-avatars/")
    assert p1 == p2
    assert p1 != p3
    assert p1.startswith("/tmp/cache-avatars/")
    assert p1.endswith(".png")


def test_cache_path_hashes_url():
    import hashlib

    url = "https://x/a.png"
    digest = hashlib.sha1(url.encode()).hexdigest()
    assert digest in avatar_cache_path(url, "/tmp/c/")
