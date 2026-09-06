"""ROUTER — the LOCAL API ACCESS surface (ledger S32): named API keys, and the honest
request log behind the API page.

WHY THIS EXISTS. Every app we embed asks for a key in its own Add-Provider form — goose
UI, Odysseus and OpenCode were all screenshot-confirmed doing exactly that — and until
now the only key that existed was the built-in `runner.api_key`: one shared secret,
stored in the mode-0600 local secret overlay, with no way to tell which app is using it and no
way to take it back from one app without taking it back from all of them. Debi's brief:
"apps' Add-Provider forms should have real keys to consume — an additional route, no
need to remove the existing routes."

So this is ADDITIVE in the strictest sense. The built-in `runner.api_key` stays: it is
still what `start_component.sh`'s readiness poll sends and what every bridge-internal
caller uses. At launch it is combined with the named keys in a derived 0600 file,
passed only as a file path, and that derived file is unlinked after llama-server parses
it. The secret never appears in process argv.

═══ THE CONTRACT, MEASURED AT OUR PIN (llama.cpp b10662, data/llamacpp) ═══════════════

Not read from upstream docs — RUN, against our own binary, on 2026-08-29, with a scratch
llama-server on port 6799 (Parable-Qwen3-4B-Q4_K_M, launched and reaped by the tester,
pid-verified before the signal). RE-MEASURED FROM SCRATCH the same day by the second
builder on this slice — every one of the five reproduced exactly, which is why they are
stated here as facts rather than as the first builder's notes. The five facts this whole
design rests on:

  1. `--api-key-file FNAME` EXISTS at b10662. Its own --help text: "path to file
     containing API keys, one per line; lines starting with a hash are treated as
     comments". Env alias LLAMA_ARG_API_KEY_FILE.
  2. IT COMBINES WITH `--api-key`. Launched with `--api-key CLIKEY-aaa --api-key-file
     <file containing FILEKEY-bbb, FILEKEY-ccc>`: all THREE keys returned 200 on
     /v1/models; a comment line's text, an unknown key and an empty key all returned
     401. The accepted set is the UNION — which is why the built-in key keeps working
     with no migration at all.
  3. THERE IS NO HOT-RELOAD. The file is read ONCE, at argument-parse time. Measured in
     both directions on the running server: appending HOTKEY-ddd → still 401; deleting
     FILEKEY-bbb → still 200. So MINT and REVOKE both bind at the next runner start,
     and this module says so out loud rather than letting the panel imply otherwise.
     (This is the reason `pending()` and the `applied` stamp below exist at all.)
  4. `--metrics` is DISABLED BY DEFAULT and returns 501 until it is passed. With it,
     GET /metrics serves prometheus counters (prompt_tokens_total,
     tokens_predicted_total, n_decode_total, requests_processing, …) which move on a
     real completion — verified: one 8-token turn took prompt_tokens_total 0 → 37 and
     tokens_predicted_total 0 → 3. They are PROCESS-LIFETIME counters and they need the
     api key like every other endpoint on that server.
  5. A KEY FILE THAT CANNOT BE OPENED IS A FATAL ARGV ERROR. Found by trying it rather
     than by reasoning about it: `--api-key-file /nonexistent` prints `error while
     handling argument "--api-key-file": error: failed to open file` and exits BEFORE
     loading anything. That is why scripts/start_component.sh tests the file before it
     passes the flag — an ungrated flag would turn "somebody deleted data/api_keys.keys"
     into "the model lane is down and nothing says why". A comments-only file is fine.

Facts 1–5 are pinned in bridge/contract_tests/test_llama_server_contract.py (§3), which
re-measures 1, 4 and 5 on every gate run and tells a future pin-bumper to re-measure 2
and 3 by hand if the --help wording ever moves.

⚠️ WHAT llama-server DOES **NOT** EXPOSE, and the honesty this forces. There is no
per-request history endpoint at this pin: /slots is the live slot table (id, n_ctx,
is_processing) with no counters, /props is configuration, and /metrics is aggregate. The
one per-request facility is `--log-prompts-dir`, which writes USERS' PROMPTS to disk and
whose own help text says "only used for debugging" — we do not ship that, and the reason
is privacy, not effort. Therefore the request log on the API page is HONESTLY SPLIT:
per-request rows come from our own lane counters (data/analytics.db, the same table
/api/analytics has always read), and traffic from apps that call :6767 DIRECTLY — goose,
OpenCode, anything holding one of these keys — shows only in the totals. The page says
that sentence; it does not invent rows.

═══ THE STORE ════════════════════════════════════════════════════════════════════════

data/api_keys.json   the named keys, and the only place a minted secret is kept.
data/api_keys.keys   named-key launch input — one key per line, generated from the
                     store on every write, never hand-edited. start_component.sh
                     derives a temporary file containing this set + the built-in key.
data/api_keys.applied  written by scripts/start_component.sh at the moment it launches
                     the runner: the digest of the key set that launch actually got.

`pending()` is then a FACT rather than a guess: the digest of the current key set versus
the digest the running runner was launched with. That is what lets the panel say "active
after the runner restarts" and then stop saying it, with nothing to reset by hand and no
process introspection.

═══ THE AI-FRIENDLY API CHECKLIST, ROUTE BY ROUTE ════════════════════════════════════

docs/research/2026-08-29-ai-friendly-api-principles.md is binding on every route here,
and the four items that actually changed the shape of this file:

  · SEMANTIC FIELD NAMES. The log rows publish `started_at_epoch / prompt_tokens /
    completion_tokens / cached_tokens / tokens_per_second / duration_seconds` — NOT
    data/analytics.db's `ts / in_tok / out_tok / cached_tok / tps`, which are legible
    only to someone holding the schema. The unit is in the name where a unit is
    ambiguous. Translation happens once, at the boundary.
  · COUNTING HINTS. Every listing carries `count`; the log adds `total_count` (how many
    turns the table holds, `None` when it could not be counted — never a comfortable 0)
    and echoes the `limit` it actually applied, so a clamp cannot be mistaken for a
    short table. The key listing carries `remaining`, which is the number a caller
    about to mint needs and would otherwise learn only by being refused.
  · ACTIONABLE SENTENCE ERRORS. No bare status codes. The mint refusal names the limit,
    the current count and the one action that clears it; the revoke 404 names the id,
    the likeliest cause (already revoked — revoke is idempotent in effect, so a double
    click is the common way to reach it) and the route that lists the live ids.
  · SEMANTIC DOCUMENTATION AS A SURFACE. `/api/apiendpoints` + the API page's Endpoints
    section say what each route MEANS, including the two that exist and answer 501
    because this launch does not enable them — the fact an OpenAI-shaped spec gets
    wrong about a local server, and the one a chooser most needs.

Batching (checklist item 2) is deliberately NOT taken: revoke stays one key per call
because it is an armed, irreversible, security action whose UI is a two-step confirm,
and a `revoke_all` is a foot-gun with no journey behind it. Recorded as a decision, not
an omission.

THE KEYS ARE SECRETS AND ARE TREATED AS SUCH: both files are written 0600 through a
temp-and-rename, the full value is returned by exactly ONE route (the mint, once), the
listing carries names and prefixes only, revoke DELETES the secret from disk
immediately, and nothing here ever prints a key — not on an error path, not into
data/logs, and not into /api/status.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..core.appctx import ROOT, app
from ..core.procs import cfg

# ── paths ────────────────────────────────────────────────────────────────────
STORE = "data/api_keys.json"      # the named keys (the ONLY copy of a minted secret)
KEYFILE = "data/api_keys.keys"    # --api-key-file fodder, generated
APPLIED = "data/api_keys.applied" # digest the RUNNING runner was launched with

# `mot-` + 16 random bytes as hex. The prefix is deliberate: a key pasted into the wrong
# field is recognisable at a glance, and grepping a support paste for `mot-` finds a
# leak. 128 bits of entropy is not a number to think about again.
KEY_PREFIX = "mot-"
NAME_MAX = 48
# The cap on named keys. Not a resource limit — the key file is bytes — but a floor
# under a runaway caller: 64 rows is more apps than this machine will ever hold, and a
# mint loop that has lost its stop condition hits a REFUSAL WITH A SENTENCE instead of
# silently growing the file llama-server parses at every launch.
MAX_KEYS = 64

def _p(rel: str):
    return ROOT / rel


def _atomic_secret(path, text: str) -> None:
    """Write 0600, temp-and-rename. The mode is set on the TEMP file before any bytes
    are written to it, so the secret is never momentarily world-readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        try:
            tmp.unlink()
        except Exception:                                            # noqa: BLE001
            pass
        raise
    os.replace(str(tmp), str(path))
    try:
        os.chmod(str(path), 0o600)
    except Exception:                                                # noqa: BLE001
        pass


# ── the store ────────────────────────────────────────────────────────────────
def read_store() -> dict:
    """FORGIVING ON DISK (nav.py's rule verbatim). A hand-edited, truncated or
    older/newer api_keys.json must never be able to stop the panel booting or the
    runner starting — the worst it may cost is the named keys. The built-in key is
    supplied independently through the protected local-secret overlay."""
    try:
        raw = json.loads(_p(STORE).read_text(encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        return {"v": 1, "keys": []}
    if not isinstance(raw, dict):
        return {"v": 1, "keys": []}
    rows = raw.get("keys")
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        kid, key, name = r.get("id"), r.get("key"), r.get("name")
        if not (isinstance(kid, str) and isinstance(key, str) and key.strip()):
            continue
        out.append({"id": kid, "name": str(name or "")[:NAME_MAX] or "unnamed",
                    "key": key.strip(),
                    "created": str(r.get("created") or "")})
    return {"v": 1, "keys": out}


def write_store(st: dict) -> None:
    _atomic_secret(_p(STORE), json.dumps({"v": 1, "keys": st.get("keys") or []},
                                         indent=2) + "\n")
    write_keyfile(st)


def keyset(st: "dict | None" = None) -> list:
    st = st if isinstance(st, dict) else read_store()
    return [r["key"] for r in st["keys"]]


def keyfile_text(st: "dict | None" = None) -> str:
    """The file llama-server is launched against. One key per line; the header is a
    `#` comment, which b10662 ignores (fact 1) — and which is there so a human who
    finds this file knows not to hand-edit it."""
    st = st if isinstance(st, dict) else read_store()
    lines = ["# MOT Deck — generated from data/api_keys.json. Do not edit by hand.",
             "# One key per line; mint and revoke in MOT Deck -> API."]
    lines += keyset(st)
    return "\n".join(lines) + "\n"


def write_keyfile(st: "dict | None" = None) -> None:
    _atomic_secret(_p(KEYFILE), keyfile_text(st))


def digest(st: "dict | None" = None) -> str:
    """The digest of the KEY SET, not of the file — so rewording the header comment
    can never look like a key change and raise a false "restart the runner"."""
    h = hashlib.sha256()
    for k in sorted(keyset(st)):
        h.update(k.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def applied_digest() -> str:
    try:
        return _p(APPLIED).read_text(encoding="utf-8").strip()
    except Exception:                                                # noqa: BLE001
        return ""


def pending(st: "dict | None" = None) -> bool:
    """Is the running runner accepting a DIFFERENT set of keys from the one on disk?

    True after every mint and every revoke, until the runner is restarted — because
    b10662 reads the key file exactly once (fact 3). It is also True the first time
    a key is ever minted on a machine whose runner is already up, which is correct:
    that key does not work yet.

    ⚠️ THE NO-KEYS CASE IS **NOT** PENDING, AND THAT IS THE ONE EXCEPTION (live finding
    L1). On a machine that has never minted anything there is no `applied` stamp, so
    the digest comparison alone said "restart the runner to apply" about a key set that
    is EMPTY — a demand to fix a state that is already correct, standing on the first
    screen every user sees. Nothing to apply is not pending. A stamp that EXISTS and
    disagrees still is: that is the all-keys-revoked case, which genuinely needs the
    restart."""
    if not keyset(st) and not applied_digest():
        return False
    return digest(st) != applied_digest()


def _prefix(key: str) -> str:
    """What the listing shows instead of the key. Four hex characters after the
    scheme prefix — enough for a human to match a row against the value they pasted
    into an app, and 16 of the 128 bits, which is not a shortcut to anything."""
    body = key[len(KEY_PREFIX):] if key.startswith(KEY_PREFIX) else key
    return (KEY_PREFIX if key.startswith(KEY_PREFIX) else "") + body[:4] + "…"


def _clean_name(raw: str, taken: "list[str]") -> str:
    """THE AUTOCORRECT STANDARD (doctrine 5): never bounce the user back with "that
    name is taken". Control characters are stripped, the length is capped, an empty
    name becomes a dated default, and a collision gets a numeric suffix — silently,
    because the panel shows the resulting name immediately and the user can see what
    they got."""
    name = re.sub(r"[\x00-\x1f\x7f]", " ", str(raw or "")).strip()
    name = re.sub(r"\s+", " ", name)[:NAME_MAX].strip()
    if not name:
        name = "Key " + time.strftime("%Y-%m-%d")
    if name not in taken:
        return name
    for n in range(2, 200):
        cand = f"{name} ({n})"[:NAME_MAX]
        if cand not in taken:
            return cand
    return f"{name[:NAME_MAX - 8]} {secrets.token_hex(3)}"


# ── the runner facts the page shows beside the keys ──────────────────────────
def _runner_cfg() -> dict:
    rc = (cfg() or {}).get("runner")
    return rc if isinstance(rc, dict) else {}


def base_url() -> str:
    """What the user pastes into an app's Add-Provider form. `/v1` is included because
    every OpenAI-compatible client we ship a provider for expects the base to END there
    — the exact trap bridge/gooseprov.py and bridge/gooseui.py both document from the
    other side (a base already ending in /v1 produces /v1/v1/chat/completions)."""
    port = _runner_cfg().get("port")
    return f"http://127.0.0.1:{int(port)}/v1" if port else ""


def _runner_get(path: str, timeout: float = 2.0):
    """GET one runner endpoint WITH the built-in key. Everything on b10662 needs it —
    /v1/models, /slots and /metrics all 401 without one (measured). Returns
    (status, text) and never raises."""
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
    port = _runner_cfg().get("port")
    if not port:
        return 0, ""
    req = Request(f"http://127.0.0.1:{int(port)}{path}")
    key = str(_runner_cfg().get("api_key") or "")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urlopen(req, timeout=timeout) as r:                     # noqa: S310
            return r.status, r.read().decode("utf-8", "replace")
    except HTTPError as e:
        return e.code, ""
    except Exception:                                                # noqa: BLE001
        return 0, ""


_METRICS_WANTED = {
    "llamacpp:prompt_tokens_total": "prompt_tokens",
    "llamacpp:prompt_tokens_cached_total": "prompt_tokens_cached",
    "llamacpp:tokens_predicted_total": "tokens_predicted",
    "llamacpp:n_decode_total": "decodes",
    "llamacpp:requests_processing": "processing",
    "llamacpp:requests_deferred": "deferred",
    "llamacpp:predicted_tokens_seconds": "tps",
}


def parse_metrics(text: str) -> dict:
    """Prometheus text format → the handful of numbers the page shows. PURE, so the
    gate can execute it against a captured sample of our own runner's output."""
    out = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        want = _METRICS_WANTED.get(parts[0])
        if not want:
            continue
        try:
            v = float(parts[1])
        except ValueError:
            continue
        out[want] = int(v) if v == int(v) else round(v, 2)
    return out


# ── the per-request rows: OUR lanes, from the table /api/analytics already reads ──
# The lane column is a raw internal token ("direct", "agent", "chat"); these are the
# words the user recognises. An UNKNOWN lane is shown verbatim rather than bucketed
# into "other" — a lane this table has not heard of is real traffic, and renaming it
# to nothing is the small lie that makes a log untrustworthy.
LANE_LABELS = {
    "direct": "Chat",
    "chat": "Chat",
    "agent": "Agent",
    "research": "Research",
}


# ⚠️ THE PUBLISHED FIELD NAMES ARE **SEMANTIC**, NOT THE TABLE'S (the AI-friendly API
# checklist, docs/research/2026-08-29-ai-friendly-api-principles.md — Gravitee's
# "semantic field names": temperature_celsius, never temp). data/analytics.db's columns
# are `in_tok / out_tok / cached_tok / tps / ttft`, readable only by someone who already
# knows that schema. This route is a PUBLISHED surface — the API page renders it and
# anything holding a key can read it — so the translation happens HERE, once, at the
# boundary, rather than being re-derived by every consumer. `duration_seconds` carries
# its unit in its name because a bare `duration` is the classic ms-or-s ambiguity, and
# `started_at_epoch` says both WHICH end of the turn it marks and what scale it is on.
def _rows(limit: int) -> list:
    import sqlite3
    db = _p("data/analytics.db")
    if not db.exists():
        return []
    rows = []
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        try:
            cur = c.execute(
                "SELECT ts, lane, model, in_tok, out_tok, cached_tok, tps, ttft "
                "FROM turns ORDER BY ts DESC LIMIT ?", (int(limit),))
            for ts, lane, model, itok, otok, ctok, tps, ttft in cur.fetchall():
                # DURATION, DERIVED AND ONLY WHEN IT CAN BE. We store time-to-first-token
                # and tokens-per-second, not a wall clock; ttft + out/tps is the turn's
                # real length. With no tps there is no honest number, so the field is
                # None and the table prints "—" rather than a zero that reads as "fast".
                secs = None
                try:
                    if tps and float(tps) > 0:
                        secs = round(float(ttft or 0) + float(otok or 0) / float(tps), 2)
                except Exception:                                    # noqa: BLE001
                    secs = None
                rows.append({
                    "started_at_epoch": float(ts or 0),
                    "lane": str(lane or ""),
                    "lane_label": LANE_LABELS.get(str(lane or ""), str(lane or "") or "—"),
                    "model": str(model or ""),
                    "prompt_tokens": int(itok or 0),
                    "completion_tokens": int(otok or 0),
                    "cached_tokens": int(ctok or 0),
                    "tokens_per_second": round(float(tps), 1) if tps else None,
                    "duration_seconds": secs,
                })
        finally:
            c.close()
    except Exception:                                                # noqa: BLE001
        return rows
    return rows


def _rows_total() -> "int | None":
    """THE COUNTING HINT (checklist item 4 — "LLMs can't count, and can't paginate to
    a count"). `/api/apilog` returns at most `limit` rows; a consumer that needs to know
    whether it is holding ALL of them or the tip of a long table must not have to page
    through it to find out, and the API page's own "40 of 1204" line comes from here.

    None — never 0 — when the table exists but cannot be read, so "no turns yet" and
    "we could not count" stay two different answers instead of one comfortable zero."""
    import sqlite3
    db = _p("data/analytics.db")
    if not db.exists():
        return 0
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        try:
            return int(c.execute("SELECT COUNT(*) FROM turns").fetchone()[0])
        finally:
            c.close()
    except Exception:                                                # noqa: BLE001
        return None


# ── what this address actually serves, and what each route MEANS ─────────────
# THE CHECKLIST'S "SEMANTIC DOCUMENTATION" CLAUSE, MADE A SURFACE RATHER THAN A README:
# meaning and intended use, not just a spec. A person (or an agent) standing on the API
# page with a base URL and a key still has to answer "and what can I call on it?", and
# the honest answer at our pin is not "whatever OpenAI documents" — two of these routes
# EXIST and refuse, because they need launch flags our runner arm does not pass.
#
# MEASURED, 2026-08-29, against the live pinned runner (b10662) on :6767 with the
# built-in key, by POSTing `{}` to each path and reading the status apart:
#     400 = the route is served and rejected an empty body  →  "served"
#     501 = the route is served but this launch did not enable it  →  "not enabled"
#     404 = no such route at this pin  →  absent, and it is not listed
#   /v1/chat/completions 400 · /v1/completions 400 · /v1/responses 400 ·
#   /v1/embeddings 501 · /v1/rerank 501 · /tokenize 200 · /apply-template 400 ·
#   /v1/models GET 200 · /props GET 200 · /slots GET 200 · /health GET 200
#
# ⚠️ IT IS A TABLE AND **NOT** A LIVE PROBE, and that is a deliberate reversal of this
# file's usual instinct. Probing writes one `got exception:` line into data/logs/
# runner.log per path per probe — measured, by doing it — so a page that re-probed on
# its five-second poll would be a log-vomit generator pointed at the one log a user
# reads when the model misbehaves. The table is re-measured at pin bumps, and
# `enabled_by` names the flag for the two whose state the launch decides, so
# bridge/contract_tests/test_llama_server_contract.py can fence the claim from the
# start_component.sh side without a running model.
ENDPOINTS = (
    {"path": "/v1/chat/completions", "method": "POST", "served": True,
     "means": "Send a conversation, get the next message. This is the one almost "
              "every app uses."},
    {"path": "/v1/models", "method": "GET", "served": True,
     "means": "Lists the one model this runner has loaded. Apps call it to fill their "
              "model dropdown."},
    {"path": "/v1/completions", "method": "POST", "served": True,
     "means": "The older plain-text form: send a prompt, get a continuation, with no "
              "chat roles."},
    {"path": "/v1/responses", "method": "POST", "served": True,
     "means": "OpenAI's newer single-call shape. Present at this build; few local "
              "apps ask for it yet."},
    {"path": "/v1/embeddings", "method": "POST", "served": False,
     "enabled_by": "--embeddings",
     "means": "Turns text into vectors for search. This model is loaded for chat, so "
              "the route answers 501."},
    {"path": "/v1/rerank", "method": "POST", "served": False,
     "enabled_by": "--reranking",
     "means": "Re-orders search results by relevance. Off for the same reason as "
              "embeddings, and answers 501."},
)


# ── routes ───────────────────────────────────────────────────────────────────
def _public(st: dict) -> list:
    return [{"id": r["id"], "name": r["name"], "prefix": _prefix(r["key"]),
             "created": r["created"]} for r in st["keys"]]


@app.get("/api/apikeys")
def api_keys_list() -> dict:
    """Names and PREFIXES only. There is no route in this app that returns a stored
    key — the mint below is the one and only time a value crosses the wire, which is
    what makes "shown once" a property of the server rather than a habit of the UI."""
    st = read_store()
    rc = _runner_cfg()
    rows = _public(st)
    return {
        "ok": True,
        "base_url": base_url(),
        "port": rc.get("port"),
        "keys": rows,
        # COUNTING HINT (checklist item 4). This listing is never paginated, so `count`
        # is the whole truth and `limit` is what is left before the mint refuses —
        # which is the number a consumer about to mint in a loop actually needs, and
        # the one it would otherwise have to discover by being rejected.
        "count": len(rows),
        "limit": MAX_KEYS,
        "remaining": max(0, MAX_KEYS - len(rows)),
        "pending": pending(st),
        # The built-in is REPORTED, never REVEALED: not its value and not its prefix.
        # It lives in motdeck.yaml, it is what every internal caller and the readiness
        # poll use, and it cannot be revoked from here — saying so is the whole point.
        "builtin": bool(rc.get("api_key")),
        "keyfile": KEYFILE,
    }


class MintBody(BaseModel):
    # ⚠️ `Any`, NOT `str`, AND THAT IS THE AUTOCORRECT STANDARD APPLIED TO A SCHEMA
    # (adversarial finding A4). Declared `str`, a mint with `{"name": 42}` was rejected
    # by FastAPI before this module ever ran, with pydantic's raw validation blob
    # (`[{'type': 'string_type', 'loc': [...]}]`) as the message — a machine artifact,
    # not the actionable sentence the AI-friendly checklist requires, and a refusal
    # where a competent product would simply have named the key "42". `_clean_name`
    # already coerces, caps, strips and de-duplicates whatever it is handed, so the
    # tolerant type costs nothing and removes the one un-actionable error this lane
    # could produce. (The framework-wide 422 shape is a real gap, but it is every
    # route's gap and belongs to the S33 adherence audit, not to a special case here.)
    name: object = ""


@app.post("/api/apikeys")
def api_keys_mint(body: MintBody) -> dict:
    st = read_store()
    if len(st["keys"]) >= MAX_KEYS:
        # ACTIONABLE, in the checklist's exact sense: it names the limit, the count, and
        # the ONE thing that clears it. A bare 400 leaves a caller to guess whether to
        # retry, wait, or stop.
        raise HTTPException(400, f"{MAX_KEYS} named keys is the limit and you have "
                                 f"{len(st['keys'])}. Revoke one first — POST "
                                 f"/api/apikeys/{{id}}/revoke, ids from GET /api/apikeys.")
    name = _clean_name(body.name, [r["name"] for r in st["keys"]])
    key = KEY_PREFIX + secrets.token_hex(16)
    row = {"id": "k_" + secrets.token_hex(6), "name": name, "key": key,
           "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    st["keys"].append(row)
    write_store(st)
    # ⚠️ THE ONLY RESPONSE IN THIS APP THAT CARRIES A KEY. It is not logged, it is not
    # cached, and the panel shows it once with a copy button and then forgets it too.
    return {"ok": True, "id": row["id"], "name": name, "key": key,
            "prefix": _prefix(key), "created": row["created"], "pending": pending(st)}


@app.post("/api/apikeys/{kid}/revoke")
def api_keys_revoke(kid: str) -> JSONResponse:
    st = read_store()
    keep = [r for r in st["keys"] if r["id"] != kid]
    if len(keep) == len(st["keys"]):
        # ⚠️ ACTIONABLE, AND IT NAMES THE LIKELIEST CAUSE (the checklist's error rule;
        # `no such key` was the pre-checklist wording and is exactly the bare 404 it
        # bans). Revoke is IDEMPOTENT in effect — a key that is already gone is gone —
        # so the overwhelmingly common way to reach this is a double-click or a stale
        # panel, and a message that says so turns a dead end into a shrug.
        raise HTTPException(404, f"No key with id {kid!r}. It may already have been "
                                 f"revoked — GET /api/apikeys lists the current ids. "
                                 f"There "
                                 + (f"are {len(keep)} named keys." if len(keep) != 1
                                    else "is 1 named key."))
    gone = next(r for r in st["keys"] if r["id"] == kid)
    st["keys"] = keep
    write_store(st)          # the secret leaves BOTH files in this one call
    # HONEST ABOUT WHEN IT BINDS (fact 3). The row is gone from the panel immediately
    # and the secret is gone from disk immediately, but the RUNNING llama-server still
    # holds the set it was launched with. Saying "revoked" full stop would be the
    # LIE-TO-USER class; the panel renders this sentence and offers the restart.
    return JSONResponse({"ok": True, "name": gone["name"], "pending": pending(st),
                         "note": "Revoked. The running runner still accepts it until "
                                 "it restarts."})


@app.get("/api/apilog")
def api_log(limit: int = 40) -> dict:
    """The API page's request log: our per-request lane rows, plus whatever the runner
    itself will tell us about the traffic we cannot see per-request.

    THE SPLIT IS PUBLISHED, not implied: `rows` are bridge lanes only and `metrics` is
    everything the process has served since it started — panel turns AND every direct
    call from goose, OpenCode or anything else holding a key. `metrics_state` says why
    the totals are missing when they are, so the page never shows a silent blank."""
    # CLAMPED, NOT REFUSED (the autocorrect standard) — but the clamp is REPORTED back
    # as `limit`, because a caller that asked for 5,000 and silently got 200 would draw
    # exactly the wrong conclusion from a short list. Asked-for and got are both facts.
    # ⚠️ `limit=0` CLAMPS TO 1, IT DOES NOT FALL BACK TO 40 (adversarial finding A7).
    # The first draft wrote `asked or 40`, so `-5` clamped to 1 while `0` — a smaller
    # number — jumped to 40. Two neighbouring inputs, two different rules, and the
    # surprising one silently returned forty rows to a caller that asked for none.
    # A clamp must be MONOTONIC; the 40 is the default for an ABSENT parameter, which
    # FastAPI has already applied by the time this runs.
    try:
        asked = int(limit)
    except (TypeError, ValueError):
        asked = 40
    limit = max(1, min(200, asked))
    st, txt = _runner_get("/metrics")
    metrics, state = {}, "ok"
    if st == 200:
        metrics = parse_metrics(txt)
        if not metrics:
            state = "unreadable"
    elif st == 501:
        # The runner was launched WITHOUT --metrics — i.e. before this slice, or by an
        # older script. A restart fixes it; the page says exactly that.
        state = "off"
    elif st in (401, 403):
        state = "auth"
    else:
        state = "down"
    rows = _rows(limit)
    return {"ok": True, "rows": rows, "metrics": metrics,
            "metrics_state": state, "base_url": base_url(),
            # COUNTING HINTS (checklist item 4), and the honest triple: how many rows
            # came back, how many the table holds, and what limit was actually applied.
            # `total_count` is None when the table could not be counted — never 0.
            "count": len(rows), "total_count": _rows_total(), "limit": limit}


@app.get("/api/apiendpoints")
def api_endpoints() -> dict:
    """WHAT THE LOCAL ADDRESS SERVES, AND WHAT EACH ROUTE MEANS.

    The semantic-documentation half of the API page: not a spec dump (an app's own docs
    have that) but the one sentence each route needs to be CHOSEN correctly — including
    the two that exist and refuse, which is the fact an OpenAI-shaped spec would get
    wrong here. Static and pin-measured rather than probed live, because probing writes
    an exception line into runner.log per path per call; ENDPOINTS above carries the
    measurement and the reason."""
    served = [e for e in ENDPOINTS if e["served"]]
    return {"ok": True, "base_url": base_url(), "endpoints": list(ENDPOINTS),
            "count": len(ENDPOINTS), "served_count": len(served)}
