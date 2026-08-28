"""CORE — best-effort per-turn usage analytics. NEVER raises into a chat lane."""
from __future__ import annotations

import threading
from fastapi.responses import JSONResponse
from .appctx import ROOT, app


# ── usage analytics (doc-09): best-effort per-turn log → SQLite. NEVER raises into chat. ──
_analytics_lock = threading.Lock()
_analytics_pruned = False   # retention prune runs once per process (Fable QA: cap growth)

def _analytics_conn():
    import sqlite3
    global _analytics_pruned
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(ROOT / "data" / "analytics.db"), timeout=5)
    c.execute("CREATE TABLE IF NOT EXISTS turns("
              "ts REAL, day TEXT, lane TEXT, model TEXT, "
              "in_tok INTEGER, out_tok INTEGER, cached_tok INTEGER, tps REAL, ttft REAL)")
    if not _analytics_pruned:   # callers already hold _analytics_lock
        _analytics_pruned = True
        try:   # best-effort: keep the newest 5000 turns (tiny rows; unbounded otherwise)
            c.execute("DELETE FROM turns WHERE rowid NOT IN "
                      "(SELECT rowid FROM turns ORDER BY ts DESC LIMIT 5000)")
            c.commit()
        except Exception:
            pass
    return c

def log_turn(lane, model, in_tok, out_tok, cached_tok, tps, ttft):
    try:
        import time as _t
        with _analytics_lock:
            c = _analytics_conn()
            c.execute("INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?)",
                      (_t.time(), _t.strftime("%Y-%m-%d"), lane, model or "",
                       int(in_tok or 0), int(out_tok or 0), int(cached_tok or 0),
                       float(tps or 0), float(ttft or 0)))
            c.commit(); c.close()
    except Exception:
        pass  # analytics must never break the chat path

def _log_ody_metrics(tail, lane):
    # Extract the last `{"type":"metrics","data":{...}}` SSE frame from the stream tail.
    try:
        import json as _json
        for line in reversed(tail.split("\n")):
            s = line.strip()
            if s.startswith("data:"):
                s = s[5:].strip()
            if s.startswith("{") and '"metrics"' in s:
                obj = _json.loads(s)
                if obj.get("type") == "metrics":
                    d = obj.get("data") or {}
                    log_turn(lane, d.get("model"), d.get("input_tokens"),
                             d.get("output_tokens"), d.get("cached_tokens") or 0,
                             d.get("tokens_per_second"), d.get("time_to_first_token"))
                    return
    except Exception:
        pass

@app.get("/api/analytics")
def api_analytics() -> JSONResponse:
    import time as _t
    day = _t.strftime("%Y-%m-%d")
    out = {"tokens_today": 0, "turns_today": 0, "avg_tps": 0, "cache_hit_pct": None}
    try:
        with _analytics_lock:
            c = _analytics_conn()
            row = c.execute("SELECT COALESCE(SUM(out_tok),0), COUNT(*) FROM turns WHERE day=?", (day,)).fetchone()
            out["tokens_today"], out["turns_today"] = int(row[0] or 0), int(row[1] or 0)
            r2 = c.execute("SELECT AVG(tps) FROM (SELECT tps FROM turns WHERE tps>0 ORDER BY ts DESC LIMIT 20)").fetchone()
            out["avg_tps"] = round(r2[0], 1) if r2 and r2[0] else 0
            r3 = c.execute("SELECT COALESCE(SUM(cached_tok),0), COALESCE(SUM(in_tok),0) FROM turns WHERE cached_tok>0").fetchone()
            if r3 and (r3[1] or 0) > 0:
                out["cache_hit_pct"] = round(r3[0] / r3[1] * 100)
            c.close()
    except Exception as e:
        out["error"] = str(e)[:120]
    return JSONResponse(out)
