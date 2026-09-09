"""CORE — the two shared HuggingFace HTTP clients.

They sat in the model-browser lane, but the downloads lane and the starter-voice fetch
use them too, and that made the hf and downloads routers mutually dependent.
"""
from __future__ import annotations

import httpx


# ⚠️ MOVED HERE from app.py:3113-3116 by the router/core split (2026-08-28).
#    The two HuggingFace httpx clients are shared by the hf, downloads and voice
#    lanes; leaving them in the hf router made hf and downloads mutually
#    dependent.

_HF = httpx.AsyncClient(base_url="https://huggingface.co", timeout=httpx.Timeout(20, read=30))
# No base_url: the starter-voice fetch talks to datasets-server.huggingface.co AND to
# whatever signed CDN host it hands back, so this one takes absolute URLs only.
_HF_ANY = httpx.AsyncClient(timeout=httpx.Timeout(20, read=60), follow_redirects=True)
