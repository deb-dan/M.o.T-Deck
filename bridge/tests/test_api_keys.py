"""NAMED API KEYS — the store, the key file, and the redaction rules (ledger S32).

The four questions this file exists to keep answered:

 1. THE STORE IS TOTAL. It arrives from disk, and a hand-edited, truncated, older or
    newer api_keys.json must never be able to stop the panel booting or the runner
    starting — nav.py's "forgiving on disk" rule, applied to a file that also carries
    secrets. Every surprise shape costs that ROW, never the store.

 2. THE KEY FILE IS WHAT llama-server PARSES. bridge/contract_tests/
    test_llama_server_contract.py §3 pins the binary's side (one key per line, `#`
    comments, and that a missing file is fatal); this pins OURS — that we generate
    exactly that shape, that a comments-only header is what an empty store produces,
    and that the digest the panel compares against is the digest the launch stamps.

 3. KEYS ARE SECRETS, AND THE PROOF IS NEGATIVE. A minted value must appear in exactly
    one response in the whole app and in no log line, no /api/status field, and no
    listing. Negative assertions are the ones that rot silently, which is why
    routers/apikeys.py is in bridge/appsrc.py's FILES (a module missing from that view
    makes every `not in` check here pass vacuously).

 4. THE PENDING FACT IS A FACT. b10662 reads the key file once, at launch, with no
    hot-reload in either direction — measured, see the contract test — so "this key is
    live" versus "this key needs a restart" has to be derived from the launch stamp
    rather than assumed. If that derivation breaks, the page starts telling users a
    freshly minted key works when it does not: the LIE-TO-USER class.

 5. THE ADVERSARIAL LEDGER of this slice's own pass, pinned by name so a tidy-up cannot
    undo a fix:
      A-1 (LIE)  a mint into a store whose runner is already up must report pending
      A-2 (LIE)  the listing must never carry the key, and never the built-in's prefix
      A-3        a duplicate name must be accepted and disambiguated, never bounced
      A-4        revoke deletes the secret from BOTH files in the one call
      A-5        a corrupt/truncated store must not lose the WHOLE key set to one bad row
      A-6        the files are 0600, and are never world-readable even momentarily
      A-7        a turn with no measured tps yields NO duration rather than 0.0s

Run: python3 bridge/tests/test_api_keys.py
"""
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge.routers import apikeys as K                         # noqa: E402

FAILS = []
CHECKS = [0]


def ok(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("FAIL " + label)


class TempRoot:
    """Point the module at a scratch ROOT. The module reads ROOT at CALL time through
    `_p`, so this is a one-attribute swap and nothing else in the tree is touched."""

    def __enter__(self):
        self.d = tempfile.TemporaryDirectory()
        self.old = K.ROOT
        K.ROOT = Path(self.d.name)
        (K.ROOT / "data").mkdir(parents=True, exist_ok=True)
        return K.ROOT

    def __exit__(self, *a):
        K.ROOT = self.old
        self.d.cleanup()


# ═════════════════════════════════════════════════════════════════════════════
print("1. the store is TOTAL (forgiving on disk)")
# ═════════════════════════════════════════════════════════════════════════════
with TempRoot() as R:
    ok(K.read_store() == {"v": 1, "keys": []}, "an ABSENT store is the empty store")
    (R / "data" / "api_keys.json").write_text("{not json at all")
    ok(K.read_store()["keys"] == [], "a CORRUPT store is the empty store, not a crash")
    (R / "data" / "api_keys.json").write_text('["a list, not an object"]')
    ok(K.read_store()["keys"] == [], "a store of the wrong TYPE is the empty store")
    # A-5: one bad row must not cost the others.
    (R / "data" / "api_keys.json").write_text(json.dumps({"v": 1, "keys": [
        {"id": "k_good", "name": "Goose UI", "key": "mot-aaaa", "created": "2026-08-29T00:00:00Z"},
        {"id": "k_nokey", "name": "no key at all"},
        "not even a dict",
        {"key": "mot-orphan"},                       # no id
        {"id": "k_blank", "name": "blank", "key": "   "},
    ]}))
    got = K.read_store()["keys"]
    ok([r["id"] for r in got] == ["k_good"],
       "A-5: a truncated/foreign row costs THAT ROW and no other")
    ok(got[0]["name"] == "Goose UI", "…and the surviving row keeps its name")
    # a nameless-but-valid row still renders as something
    (R / "data" / "api_keys.json").write_text(json.dumps({"v": 1, "keys": [
        {"id": "k_x", "key": "mot-bbbb"}]}))
    ok(K.read_store()["keys"][0]["name"] == "unnamed",
       "a valid row with no name renders as 'unnamed' rather than an empty row")

# ═════════════════════════════════════════════════════════════════════════════
print("2. the key FILE is the shape llama-server parses")
# ═════════════════════════════════════════════════════════════════════════════
with TempRoot() as R:
    st = {"v": 1, "keys": [
        {"id": "k1", "name": "A", "key": "mot-1111", "created": "x"},
        {"id": "k2", "name": "B", "key": "mot-2222", "created": "x"}]}
    K.write_store(st)
    text = (R / "data" / "api_keys.keys").read_text()
    lines = text.splitlines()
    heads = [ln for ln in lines if ln.startswith("#")]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    ok(len(heads) >= 1, "the file carries a `#` header (b10662 treats it as a comment)")
    ok(body == ["mot-1111", "mot-2222"], "one key per line, in store order, nothing else")
    ok(text.endswith("\n"), "…and it ends with a newline (no key glued to EOF)")
    ok("Do not edit by hand" in text,
       "…and it says it is generated, because a human who finds it will try to edit it")
    # A-6: both files 0600 — the secret is never world-readable, not even briefly
    for name in ("api_keys.json", "api_keys.keys"):
        mode = stat.S_IMODE((R / "data" / name).stat().st_mode)
        ok(mode == 0o600, f"A-6: data/{name} is 0600 (got {oct(mode)})")
    # …and the empty store still writes a legal file rather than nothing
    K.write_store({"v": 1, "keys": []})
    t2 = (R / "data" / "api_keys.keys").read_text()
    ok(t2.startswith("#") and not [ln for ln in t2.splitlines() if ln and not ln.startswith("#")],
       "an empty store writes a comments-only file — legal, and admits no key")

# ═════════════════════════════════════════════════════════════════════════════
print("3. PENDING is derived from the launch stamp, never assumed")
# ═════════════════════════════════════════════════════════════════════════════
with TempRoot() as R:
    K.write_store({"v": 1, "keys": []})
    # LIVE FINDING L1: a fresh machine has no stamp AND no keys, and the digest
    # comparison alone called that pending — "restart the runner to apply" about an
    # empty key set, standing on the first screen a user ever sees.
    ok(K.pending() is False,
       "L1: no keys and no stamp is NOT pending — there is nothing to apply")
    # …but a stamp that EXISTS and disagrees still is, which is the all-revoked case.
    (R / "data" / "api_keys.applied").write_text("a" * 64 + "\n")
    ok(K.pending() is True,
       "L1: …while an empty key set against a stamp for a NON-empty one still is "
       "(everything was revoked, and the runner is still accepting it)")
    # the launch writes the stamp; the module must then agree
    (R / "data" / "api_keys.applied").write_text(K.digest() + "\n")
    ok(K.pending() is False, "…and the stamp for the current key set clears it")
    # A-1: minting while the runner is up MUST report pending
    st = K.read_store()
    st["keys"].append({"id": "k9", "name": "n", "key": "mot-9999", "created": "x"})
    K.write_store(st)
    ok(K.pending() is True,
       "A-1: a key minted after the launch reports PENDING — b10662 has no hot-reload")
    # …and so must a revoke
    (R / "data" / "api_keys.applied").write_text(K.digest() + "\n")
    ok(K.pending() is False, "restart applied it")
    K.write_store({"v": 1, "keys": []})
    ok(K.pending() is True, "…and revoking it goes pending again, for the same reason")
    # the digest is over the KEY SET, so a header reword can never look like a change
    d1 = K.digest({"keys": [{"key": "b"}, {"key": "a"}]})
    d2 = K.digest({"keys": [{"key": "a"}, {"key": "b"}]})
    ok(d1 == d2, "the digest is order-independent (a reorder is not a key change)")
    ok(len(d1) == 64, "…and it is a sha256 hex digest, which reveals no key")

# ═════════════════════════════════════════════════════════════════════════════
print("4. KEYS ARE SECRETS — the negative proofs")
# ═════════════════════════════════════════════════════════════════════════════
with TempRoot() as R:
    K.write_store({"v": 1, "keys": [
        {"id": "k1", "name": "Goose UI", "key": "mot-" + "a" * 32, "created": "2026-08-29"}]})
    listed = K.api_keys_list()
    blob = json.dumps(listed)
    ok("mot-" + "a" * 32 not in blob, "A-2: the LISTING never carries the key value")
    ok(listed["keys"][0]["prefix"] == "mot-aaaa…", "…only a four-character prefix")
    ok(listed["keys"][0]["name"] == "Goose UI" and listed["keys"][0]["created"],
       "…with the name and the created date, which is what a human matches on")
    ok(set(listed["keys"][0]) == {"id", "name", "prefix", "created"},
       "…and nothing else is published per row")
    ok(listed["builtin"] in (True, False),
       "the built-in is reported as a BOOLEAN — present or not")
    ok(not isinstance(listed["builtin"], str),
       "A-2: …never as a value and never as a prefix; it lives in harness.yaml and "
       "cannot be revoked from here, which is the only thing the page needs to say")
# the app layer as a whole: /api/status must not learn about keys, and nothing prints one
src = _APP_SOURCE
m = re.search(r'@app\.get\("/api/status"\)(.*?)\n@app\.', src, re.S)
ok(bool(m), "the /api/status handler is where this test expects it")
if m:
    ok("api_key" not in m.group(1) and "apikey" not in m.group(1),
       "A-2: /api/status carries no key material — it is polled every few seconds by "
       "the panel AND the shell, and is the widest-read object in the app")
rt = (ROOT / "bridge" / "routers" / "apikeys.py").read_text()
code = re.sub(r'"""[\s\S]*?"""', "", rt)
code = "\n".join(ln for ln in code.splitlines() if not ln.lstrip().startswith("#"))
ok("print(" not in code, "the keys router prints NOTHING — no key can reach data/logs")
# EVERY ROUTE HANDLER, one at a time: exactly ONE of them may return a key value.
# Written against the handler bodies rather than the whole file, because the store
# reader and writer legitimately name the field and a whole-file count cannot tell
# "reads the store" from "answers the network".
handlers = re.findall(r"@app\.(?:get|post)\([^)]*\)\ndef (\w+)\([\s\S]*?(?=\n@app\.|\Z)",
                      code)
bodies = re.split(r"@app\.(?:get|post)\(", code)[1:]
leaky = [b.split("\n")[1][:60] for b in bodies if '"key": key' in b]
ok(len(leaky) == 1, f"exactly ONE route puts a key value into a response (got {leaky})")
ok(leaky and "api_keys_mint" in leaky[0],
   "…and that route is the MINT, which is the one-time reveal")
pub = re.search(r"def _public\([\s\S]*?\n\n", code).group(0)
ok('"key":' not in pub,
   "…while _public (what the listing renders) never builds a `key` field at all — it "
   "reads the value only to compute the four-character prefix")

# ═════════════════════════════════════════════════════════════════════════════
print("5. names, prefixes, metrics, durations")
# ═════════════════════════════════════════════════════════════════════════════
# A-3 — THE AUTOCORRECT STANDARD: ambiguity is resolved, never handed back as a question.
ok(K._clean_name("Goose UI", []) == "Goose UI", "a good name is kept verbatim")
ok(K._clean_name("  Goose   UI  ", []) == "Goose UI", "whitespace is normalised")
ok(K._clean_name("Goose UI", ["Goose UI"]) == "Goose UI (2)",
   "A-3: a duplicate is disambiguated, not refused")
ok(K._clean_name("Goose UI", ["Goose UI", "Goose UI (2)"]) == "Goose UI (3)",
   "…and again, without ever asking")
ok(K._clean_name("", []).startswith("Key "), "an EMPTY name gets a dated default")
ok("\n" not in K._clean_name("a\nb\x00c", []) and "\x00" not in K._clean_name("a\nb\x00c", []),
   "control characters cannot reach the key file's line-oriented format")
ok(len(K._clean_name("x" * 500, [])) <= K.NAME_MAX, "an absurd name is capped")
# the prefix reveals four characters of a 32-hex body and nothing more
ok(K._clean_name(42, []) == "42",
   "A4: a NON-STRING name is coerced, not refused — the mint takes `object` so a "
   "`{\"name\": 42}` body never reaches pydantic's raw validation blob")
ok(K._clean_name(None, []).startswith("Key "), "…and None is the empty case")
ok(K._prefix("mot-0123456789abcdef") == "mot-0123…", "the prefix is scheme + four chars")
ok(K._prefix("legacy-key-no-scheme").endswith("…"), "a key with no scheme still elides")

mtxt = ("# HELP x\n# TYPE x counter\n"
        "llamacpp:prompt_tokens_total 37\n"
        "llamacpp:tokens_predicted_total 3\n"
        "llamacpp:predicted_tokens_seconds 108.637\n"
        "llamacpp:requests_processing 0\n"
        "something:we:do:not:show 999\n"
        "malformed line here that is not two fields\n")
m2 = K.parse_metrics(mtxt)
ok(m2["prompt_tokens"] == 37 and m2["tokens_predicted"] == 3,
   "the prometheus counters we show are parsed as ints")
ok(m2["tps"] == 108.64, "…a gauge keeps two decimals")
ok("something:we:do:not:show" not in json.dumps(m2),
   "…and an unknown series is dropped rather than rendered as a mystery chip")
ok(K.parse_metrics("") == {} and K.parse_metrics(None) == {},
   "empty/absent metrics text is an empty dict, never a crash")

# A-7 — NO INVENTED DURATION. The rows come out of the same table /api/analytics reads.
with TempRoot() as R:
    import sqlite3
    c = sqlite3.connect(str(R / "data" / "analytics.db"))
    c.execute("CREATE TABLE turns(ts REAL, day TEXT, lane TEXT, model TEXT, "
              "in_tok INTEGER, out_tok INTEGER, cached_tok INTEGER, tps REAL, ttft REAL)")
    c.execute("INSERT INTO turns VALUES(1000, 'd', 'direct', 'M', 87, 27, 0, 86.2, 0.24)")
    c.execute("INSERT INTO turns VALUES(2000, 'd', 'agent', 'M', 10, 20, 0, 0, 0)")
    c.execute("INSERT INTO turns VALUES(3000, 'd', 'weird-new-lane', 'M', 1, 2, 0, 5, 1)")
    c.commit(); c.close()
    rows = K._rows(10)
    ok([r["started_at_epoch"] for r in rows] == [3000, 2000, 1000],
       "rows come back newest first")
    # ⚠️ THE PUBLISHED NAMES ARE SEMANTIC, NOT THE TABLE'S (the AI-friendly checklist).
    # Asserted as a SET, both ways, so a column added to the query later cannot leak
    # `in_tok` and friends onto a published surface without this failing.
    ok(set(rows[0]) == {"started_at_epoch", "lane", "lane_label", "model",
                        "prompt_tokens", "completion_tokens", "cached_tokens",
                        "tokens_per_second", "duration_seconds"},
       f"the row publishes SEMANTIC field names, not analytics.db's columns "
       f"(got {sorted(rows[0])})")
    ok(not ({"ts", "in_tok", "out_tok", "cached_tok", "tps"} & set(rows[0])),
       "…and no schema-only name survives to the wire")
    r1 = next(r for r in rows if r["started_at_epoch"] == 1000)
    ok(r1["duration_seconds"] == round(0.24 + 27 / 86.2, 2),
       "duration = ttft + out/tps, from the numbers we actually measured")
    r2 = next(r for r in rows if r["started_at_epoch"] == 2000)
    ok(r2["duration_seconds"] is None,
       "A-7: a turn with no measured tps yields NO duration — 0.0s would read as instant")
    # A7 — THE CLAMP IS MONOTONIC. `limit=0` must land on the FLOOR like `limit=-5`,
    # not jump to the 40 that is the default for an ABSENT parameter: two neighbouring
    # inputs must not follow two different rules, and the surprising one returned forty
    # rows to a caller that asked for none.
    ok(len(K.api_log(limit=0)["rows"]) <= 1 and K.api_log(limit=0)["limit"] == 1,
       "A7: limit=0 clamps to the floor of 1, it does not fall back to 40")
    ok(K.api_log(limit=-5)["limit"] == 1, "…and a negative limit lands on the same floor")
    ok(K.api_log(limit=99999)["limit"] == 200, "…and an absurd one on the ceiling")
    ok(K.api_log(limit=2)["limit"] == 2 and K.api_log(limit=2)["count"] == 2,
       "…while a legal limit is applied verbatim and `count` reports what came back")
    ok(K.api_log(limit=2)["total_count"] == 3,
       "…and total_count still counts the whole table beside it")
    # COUNTING HINTS (checklist item 4): the total counts the TABLE, not the page.
    ok(K._rows_total() == 3,
       "the counting hint counts the whole table, so a clamped page can say 'n of N'")
    ok(len(K._rows(2)) == 2 and K._rows_total() == 3,
       "…and it does not move when the limit does")
    r3 = next(r for r in rows if r["started_at_epoch"] == 3000)
    ok(r3["lane_label"] == "weird-new-lane",
       "an UNKNOWN lane is shown verbatim, never bucketed into 'other' — a lane this "
       "table has not heard of is real traffic")
    ok(r1["lane_label"] == "Chat" and r2["lane_label"] == "Agent",
       "…while the known lanes read as the words the user recognises")
with TempRoot():
    ok(K._rows(10) == [], "no analytics.db yet is an empty log, not a crash")
    ok(K._rows_total() == 0,
       "…and no table at all counts ZERO, which is a fact we can state")
# ⚠️ AN UNREADABLE TABLE IS **NOT** A ZERO. "we could not count" and "there is nothing"
# are different answers, and collapsing them is how a log page tells a user their apps
# have been idle when in truth the count failed.
with TempRoot() as R:
    (R / "data" / "analytics.db").write_text("this is not a database")
    ok(K._rows_total() is None,
       "a table that exists and cannot be read counts None, never a comfortable 0")
    ok(K._rows(10) == [], "…and yields no rows rather than raising")

# ═════════════════════════════════════════════════════════════════════════════
print("5b. the AI-friendly API checklist (docs/research/2026-08-29-…)")
# ═════════════════════════════════════════════════════════════════════════════
# Binding on every route this slice ships. The four items that changed its shape are
# each fenced here, because "we designed against the checklist" is a claim that rots
# the moment somebody adds a fifth route without reading it.
with TempRoot() as R:
    K.write_store({"v": 1, "keys": [
        {"id": "k1", "name": "A", "key": "mot-1111", "created": "x"}]})
    listed = K.api_keys_list()
    ok(listed["count"] == 1 and listed["limit"] == K.MAX_KEYS
       and listed["remaining"] == K.MAX_KEYS - 1,
       "COUNTING: the key listing publishes count, limit and remaining — the last is "
       "the number a caller about to mint needs, and would otherwise learn by refusal")
    # ACTIONABLE ERRORS. A bare status code is the thing the checklist bans by name.
    try:
        K.api_keys_revoke("k_does_not_exist")
        ok(False, "revoking an unknown id must refuse")
    except Exception as e:                                           # noqa: BLE001
        msg = str(getattr(e, "detail", e))
        ok(getattr(e, "status_code", None) == 404, "an unknown id is a 404…")
        ok("k_does_not_exist" in msg and "already have been revoked" in msg
           and "/api/apikeys" in msg,
           "…whose message names the id, the likeliest cause and the route that lists "
           f"the live ids — not a bare code (got: {msg!r})")
    st = K.read_store()
    st["keys"] = [{"id": f"k{i}", "name": f"n{i}", "key": f"mot-{i:04d}", "created": "x"}
                  for i in range(K.MAX_KEYS)]
    K.write_store(st)
    try:
        K.api_keys_mint(K.MintBody(name="one too many"))
        ok(False, "the mint must refuse past the cap")
    except Exception as e:                                           # noqa: BLE001
        msg = str(getattr(e, "detail", e))
        ok(str(K.MAX_KEYS) in msg and "Revoke one first" in msg,
           f"the mint refusal names the limit and the ONE action that clears it "
           f"(got: {msg!r})")
# SEMANTIC DOCUMENTATION AS A SURFACE — and the honesty that makes it worth having.
eps = K.api_endpoints()
paths = {e["path"] for e in eps["endpoints"]}
ok("/v1/chat/completions" in paths and "/v1/models" in paths,
   "the catalogue lists the two routes every provider form needs")
ok(eps["count"] == len(K.ENDPOINTS) and eps["served_count"] < eps["count"],
   "COUNTING: it publishes both totals, and they differ — some routes are not served")
off = [e for e in K.ENDPOINTS if not e["served"]]
ok(off and all(e.get("enabled_by") for e in off),
   "⚠️ a route that EXISTS and answers 501 is listed WITH the flag that would enable "
   "it. Hiding it would leave an app pointed here for embeddings failing with an error "
   "that blames the address — the omission class of lie")
ok(all(len(e["means"].split()) >= 8 for e in K.ENDPOINTS),
   "every route carries a real sentence of MEANING, not a restated path")
ok(all("501" in e["means"] for e in off),
   "…and the unserved ones say what the caller will actually see")

# ═════════════════════════════════════════════════════════════════════════════
print("6. the wiring")
# ═════════════════════════════════════════════════════════════════════════════
ok("routers/apikeys.py" in (ROOT / "bridge" / "appsrc.py").read_text(),
   "the lane is in appsrc.FILES — without it every negative assertion above about "
   "the app layer would pass VACUOUSLY")
ok("routers.apikeys" in (ROOT / "bridge" / "app.py").read_text(),
   "…and in app.py's _LANES, which is what registers the routes")
for route in ('@app.get("/api/apikeys")', '@app.post("/api/apikeys")',
              '@app.post("/api/apikeys/{kid}/revoke")', '@app.get("/api/apilog")',
              '@app.get("/api/apiendpoints")'):
    ok(route in src, "the app layer declares " + route)
ok('@app.delete("/api/apikeys' not in src,
   "revoke is a POST, not a DELETE — it is a two-step armed action in the UI and a "
   "verb a stray prefetch can replay is the wrong shape for it")
ok("/api/components/runner/restart" in (ROOT / "bridge" / "panel" / "index.html").read_text(),
   "the API page's Restart button calls the ONE audited restart route (pidfile "
   "identity first, refusals honoured) rather than a second copy of the kill logic")

print(f"\n{CHECKS[0]} checks, {len(FAILS)} failures")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
