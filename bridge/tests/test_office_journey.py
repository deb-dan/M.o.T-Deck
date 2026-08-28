"""THE GOLDEN-JOURNEY TEST — Debi's whole user story, server-side, with no model.

═══ THIS FILE IS A TEMPLATE. READ THIS BEFORE ADDING A JOURNEY. ═══

Every other office suite in this repo tests a LAYER: test_office_lane.py tests the
mapper, test_office_mcp.py tests the tool surface and the changeset store, and
test_office_ai.js tests the page's pure functions. All of them were GREEN on the morning
of 2026-08-28, and the product was still broken — because the bug lived in the SEAM. The
agent staged `"$2,500"`; the validator accepted it verbatim (correctly, by its own
contract); the dry-run reported it faithfully; `=SUM(B2:B12)` was written exactly as
asked; and the total came out 0. Not one layer was wrong. The JOURNEY was.

So the rule this file exists to enforce, and the reason it is the template:

    ⚠️ A NEW CAPABILITY ON THIS LANE IS NOT DONE UNTIL THE WHOLE USER STORY RUNS HERE,
       END TO END, WITH NO MODEL IN IT.

WHAT A JOURNEY IN THIS FILE LOOKS LIKE, and every one of the five below follows it:
  1. Start from a REAL WORKBOOK ON DISK (or from create_workbook, as the agent would).
  2. Call office_ops EXACTLY AS THE AGENT WOULD — stage_changes with the same op list a
     model emits, strings and all. Never reach past the tool surface into a helper: the
     bug was in what the tool surface did with plausible input.
  3. ASSERT WHAT DEBI WOULD SEE: the card's before → after rows, the notes, the warnings.
  4. APPLY, then RE-READ WITH openpyxl. Not our own snapshot reader — an independent one,
     because "we wrote what we meant to" is the claim under test, not the evidence.
  5. ASSERT THE TYPES, not just the values. `type(cell.value) is int` and
     `cell.number_format` are what the 2026-08-28 incident turned on.
  6. ASSERT THE NEGATIVE PATH TOO: the condition that SHOULD warn, warning; and the
     condition that should NOT warn, staying silent. A detector that fires on everything
     is the same as one that fires on nothing.

WHAT IT DELIBERATELY DOES NOT DO: it does not run a model, and it does not open a
browser. Those are the LIVE proof, and they are a separate gate (a screenshot in the ship
report). This file has to be fast enough that nobody is tempted to skip it.

Run: python3 bridge/tests/test_office_journey.py   (from the repo root)
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "bridge"))

import office            # noqa: E402
import office_ops as oo  # noqa: E402

try:
    import openpyxl      # noqa: E402
except ImportError:                                            # pragma: no cover
    print("CANNOT RUN: openpyxl is not installed in this interpreter")
    sys.exit(2)

PASS = 0
FAIL = []


def check(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print("PASS", name)
    else:
        FAIL.append(name)
        print("FAIL:", name, ("— " + str(extra)) if extra else "")


def eq(name, got, want):
    check(name, got == want, f"got {got!r}, want {want!r}")


class Bench:
    """A throwaway harness root with a data/office in it, and nothing else."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="journey-")
        os.makedirs(os.path.join(self.root, "data", "office"), exist_ok=True)
        oo.changeset_clear()
        oo.clear_sessions()
        oo.heartbeat_clear()

    def path(self, name):
        return os.path.join(self.root, "data", "office", name)

    def sheet(self, name):
        """The workbook re-read by openpyxl — an INDEPENDENT reader, deliberately."""
        wb = openpyxl.load_workbook(self.path(name))
        return wb.active

    def drop(self):
        shutil.rmtree(self.root, ignore_errors=True)


def stage(bench, ops, name="Budget.xlsx", session="journey", sheet=None):
    res, err = oo.stage_changes(bench.root, session, name, sheet, ops)
    check(f"stage_changes accepted the ops ({name})", err is None, err)
    return res


def apply(bench, res):
    got, err = oo.apply_changeset(bench.root, res["changeset_id"])
    check("apply_changeset landed", err is None, err)
    return got


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 1 — THE INCIDENT ITSELF, RUN FORWARD UNTIL IT WORKS
#
# "make me a monthly budget with dollar amounts"  →  "now sum it up"
#
# This is Debi's transcript of 2026-08-28, op for op: the agent staged the amounts as
# money STRINGS (which is what a 27B does, and the whole reason the writer has to cope),
# and then staged a =SUM over them in a second turn. What must come out the far end is a
# workbook where the amounts are NUMBERS, the format is currency, the formula is a
# formula, and the range it sums is numeric — i.e. a total that is not 0.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 1: the budget, staged as money strings, summed in a second turn ═══")
b = Bench()
ROWS = [("Rent", "$2,500"), ("Groceries", "$400"), ("Utilities", "$200"),
        ("Transportation", "$180"), ("Dining & Entertainment", "$300"),
        ("Internet & Phone", "$120"), ("Subscriptions", "$60"), ("Gym/Fitness", "$50"),
        ("Health Insurance", "$275"), ("Miscellaneous", "$150"),
        ("Savings Goal", "$500")]
WANT_TOTAL = 2500 + 400 + 200 + 180 + 300 + 120 + 60 + 50 + 275 + 150 + 500

turn1 = stage(b, [
    {"op": "create_workbook"},
    {"op": "set", "at": "A1", "values": [["Item", "Planned", "Actual", "Variance"]]},
    {"op": "set", "at": "A2", "values": [list(r) for r in ROWS]},
    {"op": "style", "at": "A1:D1", "set": {"bl": 1}},
])

# ── what DEBI sees on the card, before she has pressed anything ──
co = {c["ref"]: c for c in turn1["coerced"]}
# In ROW ORDER, not sorted() — 'B10' sorts before 'B2' as a string, and a test that
# compared them alphabetically would be asserting the wrong thing on purpose.
eq("every money string was coerced, and the coercion is on the changeset for the card",
   [c["ref"] for c in turn1["coerced"]],
   ["B" + str(i + 2) for i in range(len(ROWS))])
eq("…to the right number with the right format", [co["B2"]["v"], co["B2"]["n"]],
   [2500, "$#,##0"])
eq("nothing was kept as text — a 'Planned' column of money is money", turn1["kept_text"],
   [])
pv = {p["ref"]: p for p in turn1["preview"]}
# ⚠️ DEBI'S OWN RULING: "never a coercion the card didn't show". The row carries the
# STAGED STRING and the STORED number with its format, which is what the panel prints as
#   B2  "$2,500"  →  2500 ($#,##0)
check("the preview row SHOWS the coercion: the staged string, the stored number, the "
      "format",
      pv["B2"]["coerced"] is True and pv["B2"]["coerced_from"] == "$2,500"
      and pv["B2"]["after_display"] == "2500 ($#,##0)", pv["B2"])
check("…and the note says it in words, so it is not only in a structured field",
      any("stored as real NUMBERS" in n and 'B2 \'$2,500\' → 2500 ($#,##0)' in n
          for n in turn1["notes"]), turn1["notes"])
eq("staging the amounts raises NO aggregate warning — there is no aggregate in it yet",
   turn1["warnings"], [])
check("and staging still wrote nothing: the workbook does not exist yet",
      not os.path.isfile(b.path("Budget.xlsx")))

r1 = apply(b, turn1)
check("the receipt verifies by re-reading the file", r1["verify"] and all(
    v["match"] for v in r1["verify"]), r1["verify_note"])

# ── the file, read by openpyxl and not by us ──
ws = b.sheet("Budget.xlsx")
eq("B2 is a NUMBER on disk, not a string — THE root fix",
   [type(ws["B2"].value).__name__, ws["B2"].value], ["int", 2500])
eq("…with the currency format, so it still LOOKS like what the agent wrote",
   ws["B2"].number_format, "$#,##0")
check("every amount is numeric", all(
    isinstance(ws.cell(row=i + 2, column=2).value, (int, float))
    for i in range(len(ROWS))))
check("…and every one carries the currency format", all(
    ws.cell(row=i + 2, column=2).number_format == "$#,##0" for i in range(len(ROWS))))
eq("the labels are still text", ws["A2"].value, "Rent")

# ── TURN 2: "now sum it up" ──
turn2 = stage(b, [
    {"op": "set", "at": "A13", "values": [["TOTALS", "=SUM(B2:B12)", "=SUM(C2:C12)"]]},
    {"op": "set", "at": "D13", "values": [["=C13-B13"]]},
])
# ⚠️⚠️ THE ASSERTION THIS WHOLE FILE WAS BUILT AROUND. The amounts are already real
# numbers, so the dry-run finds nothing to warn about — the warning is precisely "this
# SUM will read text", never "this SUM looks risky".
eq("NO aggregate-over-text warning fires, because the coercion already happened",
   turn2["warnings"], [])
check("…and no note pretends otherwise",
      not any("looks numeric" in n for n in turn2["notes"]), turn2["notes"])
r2 = apply(b, turn2)

ws = b.sheet("Budget.xlsx")
eq("the formula is a FORMULA in the file", ws["B13"].value, "=SUM(B2:B12)")
eq("…and so is the variance", ws["D13"].value, "=C13-B13")
# ⚠️ WE DO NOT CLAIM THE COMPUTED VALUE HERE, AND THAT IS AN HONEST LIMIT WRITTEN DOWN:
# openpyxl does not evaluate formulas and neither does the bridge. What CAN be proven
# server-side is that the summed range is numeric — which is the thing that was false on
# 2026-08-28 and is the only reason the total was 0. The COMPUTED number is proven in the
# editor (bridge/panel/oo.html::readCells → the receipt's "computed:" line) and in the
# live proof.
summed = [ws.cell(row=i + 2, column=2).value for i in range(len(ROWS))]
check("the range the SUM reads is entirely numeric — the fact the 0 came from",
      all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in summed),
      summed)
eq("…and it adds up to what Debi asked for", sum(summed), WANT_TOTAL)
b.drop()


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 2 — THE NEGATIVE PATH: a hand-crafted TEXT workbook, and a SUM over it
#
# The warning has to FIRE, and it has to NAME THE RANGE. This fixture is byte-for-byte
# the shape of Debi's live Untitled.xlsx as openpyxl found it: every B cell a str, every
# number_format General.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 2: a text-typed workbook — the warning MUST fire ═══")
b = Bench()
wb = openpyxl.Workbook()
sh = wb.active
sh["A1"], sh["B1"] = "Item", "Planned"
for i, (label, amount) in enumerate(ROWS):
    sh.cell(row=2 + i, column=1, value=label)
    sh.cell(row=2 + i, column=2, value=amount)          # a STRING, on purpose
wb.save(b.path("Incident.xlsx"))
pre = b.sheet("Incident.xlsx")
check("the fixture really is the incident: B2 is a str with General format",
      isinstance(pre["B2"].value, str) and pre["B2"].number_format == "General")

w = stage(b, [{"op": "set", "at": "A13", "values": [["TOTALS", "=SUM(B2:B12)"]]}],
          name="Incident.xlsx")
eq("exactly one warning, for the one aggregate staged", len(w["warnings"]), 1)
g = w["warnings"][0]
eq("it names the RANGE, the FUNCTION and the cell the formula lands in",
   [g["range"], g["fn"], g["ref"], g["kind"]],
   ["B2:B12", "SUM", "B13", "aggregate_over_text"])
eq("…and every text cell in it, so nothing has to be guessed at", g["count"], 11)
eq("…listing them by reference", g["cells"], ["B" + str(i + 2) for i in range(11)])
check("the CARD's sentence states the consequence and does NOT ask Debi a question — "
      "a type decision is not hers to make in a dialog box (her ruling, 2026-08-28)",
      "hold text that looks numeric" in g["sentence"]
      and "will compute 0" in g["sentence"]
      and "?" not in g["sentence"] and "your call" not in g["sentence"], g["sentence"])
check("the MODEL's sentence is an INSTRUCTION it can act on this turn",
      "restage them as JSON numbers" in g["instruction"]
      and "B2:B12" in g["instruction"], g["instruction"])
check("…and it reaches the tool result, where the model will actually read it",
      any(g["instruction"] in n for n in w["notes"]), w["notes"])
check("…next to the remedy, which names BOTH outcomes and tells it not to ask Debi",
      any("FIX IT NOW, IN THIS TURN" in n and "Do not ask Debi" in n
          for n in w["notes"]))
# THE FALSE-POSITIVE HALF. A detector that fires on everything is the same as one that
# fires on nothing, so the shapes that must stay silent are pinned here.
quiet = stage(b, [{"op": "set", "at": "D1", "values": [["Note"], ["see B12"]]}],
              name="Incident.xlsx")
eq("text that is NOT inside an aggregate raises nothing — the warning is about a "
   "formula's range, not about the sheet having text in it", quiet["warnings"], [])
noagg = stage(b, [{"op": "set", "at": "D2", "values": [["=B2&\" total\""]]}],
              name="Incident.xlsx")
eq("a formula that is not an aggregate raises nothing", noagg["warnings"], [])
eq("an aggregate over a range with no text raises nothing",
   stage(b, [{"op": "set", "at": "D3", "values": [["=SUM(D1:D1)"]]}],
         name="Incident.xlsx")["warnings"], [])
b.drop()


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 3 — THE SELF-HEAL: the model reads the warning and fixes it in one turn
#
# ⚠️ THIS IS THE ONE DEBI'S AMENDMENT 2 ADDED, AND IT IS THE ONE THAT MATTERS MOST: the
# aggregate-over-text condition must be repaired BY THE MODEL, inside its own turn, from
# the instruction in its tool result — not by a question put to Debi and not by a button
# on the card. The model is not run here; its INSTRUCTION is followed literally, which is
# the honest server-side half of that claim.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 3: the model follows the instruction and re-stages typed ═══")
b = Bench()
wb = openpyxl.Workbook()
sh = wb.active
sh["A1"], sh["B1"] = "Item", "Planned"
for i, (label, amount) in enumerate(ROWS):
    sh.cell(row=2 + i, column=1, value=label)
    sh.cell(row=2 + i, column=2, value=amount)
wb.save(b.path("Heal.xlsx"))

bad = stage(b, [{"op": "set", "at": "A13", "values": [["TOTALS", "=SUM(B2:B12)"]]}],
            name="Heal.xlsx")
check("the turn that would have gone wrong is warned", len(bad["warnings"]) == 1)

# THE MODEL'S OWN MOVE, exactly as AGG_TEXT_FIX describes it: re-set those cells as JSON
# NUMBERS with a number-format style op, AND re-state the formula, in ONE call. That call
# REPLACES the warned proposal (spec §1) — Debi never sees the bad one.
healed = stage(b, [
    {"op": "set", "at": "B2", "values": [[float(a.replace("$", "").replace(",", ""))]
                                         for _lbl, a in ROWS]},
    {"op": "style", "at": "B2:B12", "set": {"n": {"pattern": "$#,##0"}}},
    {"op": "set", "at": "A13", "values": [["TOTALS", "=SUM(B2:B12)"]]},
], name="Heal.xlsx")
eq("the re-stage carries NO warning: typed values are what the instruction asked for",
   healed["warnings"], [])
check("…and it REPLACED the warned proposal rather than adding a second card",
      healed["replaced"] is True
      and oo.get_changeset(bad["changeset_id"]) is None)
r = apply(b, healed)
ws = b.sheet("Heal.xlsx")
check("the amounts are numbers on disk", all(
    isinstance(ws.cell(row=i + 2, column=2).value, (int, float)) for i in range(11)))
eq("…with the currency format the style op asked for", ws["B2"].number_format, "$#,##0")
eq("…and the total's range now sums to the real number",
   sum(ws.cell(row=i + 2, column=2).value for i in range(11)), WANT_TOTAL)
eq("ZERO questions were put to the user anywhere in this journey — no field on any of "
   "the three staging results asks her to decide a type",
   [k for k in ("question", "ask_user", "needs_decision", "prompt")
    if k in bad or k in healed], [])
b.drop()


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 4 — KEEP AS TEXT: phone numbers, ids and an explicit apostrophe
#
# The mirror image, and the reason coercion is not a hard rule. A phone-number column
# must survive a writer that has just been taught to see numbers everywhere — with NO
# question asked, and NO coercion shown on the card, because none happened.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 4: ids and phone numbers stay text, silently and correctly ═══")
b = Bench()
staff = stage(b, [
    {"op": "create_workbook"},
    {"op": "set", "at": "A1", "values": [
        ["Name", "Phone", "Employee ID", "Ext"],
        ["Ann Kask", "(555) 010-1234", "007", "0042"],
        ["Bo Tamm", "(555) 010-9999", "0128", "0175"]]},
], name="Staff.xlsx")
eq("nothing in a phone/id table was coerced", staff["coerced"], [])
eq("…and nothing had to be kept back by inference either: those SHAPES cannot coerce at "
   "all, which is the hard guard doing its job before any judgement is involved",
   staff["kept_text"], [])
apply(b, staff)
ws = b.sheet("Staff.xlsx")
for ref, want in (("B2", "(555) 010-1234"), ("C2", "007"), ("D2", "0042"),
                  ("C3", "0128")):
    eq(f"{ref} is the exact string the agent wrote", ws[ref].value, want)
    eq(f"…and {ref} is stored as a str, not a renumbered id",
       type(ws[ref].value).__name__, "str")

# THE TWO EXPLICIT ESCAPE HATCHES, on a shape that WOULD otherwise coerce.
esc = stage(b, [
    {"op": "set", "at": "F1", "values": [["Band"], ["'$2,500"], ["'$1,000"]]},
    {"op": "set", "at": "G1", "as_text": True, "values": [["Tier"], ["$2,500"]]},
], name="Staff.xlsx")
eq("a leading apostrophe and as_text both defeat the coercion completely",
   esc["coerced"], [])
check("…and the op list SAYS which op was verbatim text, so the card can too",
      any("as TEXT, verbatim" in s for s in esc["op_list"]), esc["op_list"])
pv = {p["ref"]: p for p in esc["preview"]}
check("a kept-as-text numeric-looking value renders QUOTED on the card — the type is "
      "visible without anybody being asked about it",
      pv["F2"]["after_display"] == '"$2,500"'
      and pv["G2"]["after_display"] == '"$2,500"', pv)
check("…and NO coercion is shown for them, because none happened",
      pv["F2"]["coerced"] is False and pv["G2"]["coerced"] is False)
apply(b, esc)
ws = b.sheet("Staff.xlsx")
eq("the apostrophe was STRIPPED and the text kept", ws["F2"].value, "$2,500")
eq("…as a string", type(ws["F2"].value).__name__, "str")
eq("as_text kept it verbatim too", ws["G2"].value, "$2,500")
eq("…and neither gained a currency format", [ws["F2"].number_format,
                                             ws["G2"].number_format],
   ["General", "General"])
b.drop()


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 5 — INFERENCE, WHERE IT HAS TO CHOOSE
#
# A numeric-shaped string in a column whose CONTEXT says text. Nobody is asked; the
# decision is recorded with its reason so the card can state it.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 5: context decides, automatically, and says why ═══")
b = Bench()
wb = openpyxl.Workbook()
sh = wb.active
sh["A1"], sh["B1"] = "Product", "Ref"
for i, v in enumerate(["AB-100", "AB-200", "AB-300"]):
    sh.cell(row=2 + i, column=1, value=f"P{i}")
    sh.cell(row=2 + i, column=2, value=v)
wb.save(b.path("Refs.xlsx"))
inf = stage(b, [{"op": "set", "at": "B5", "values": [["$2,500"]]}], name="Refs.xlsx")
eq("a money-shaped string appended to a column of 'AB-100' refs stays TEXT",
   [k["ref"] for k in inf["kept_text"]], ["B5"])
check("…and the REASON is recorded, in words, rather than a question being asked",
      "already holds mostly text" in inf["kept_text"][0]["why"]
      and "reads as an identifier" in inf["kept_text"][0]["why"],
      inf["kept_text"][0]["why"])
apply(b, inf)
eq("…so the file holds the string", b.sheet("Refs.xlsx")["B5"].value, "$2,500")

# AND THE OTHER WAY, on the same shape: a column that already holds numbers keeps them.
b2 = Bench()
wb = openpyxl.Workbook()
sh = wb.active
sh["A1"], sh["B1"] = "Item", "Amount"
for i, v in enumerate([100, 200, 300]):
    sh.cell(row=2 + i, column=2, value=v)
wb.save(b2.path("Amts.xlsx"))
num = stage(b2, [{"op": "set", "at": "B5", "values": [["$2,500"]]}], name="Amts.xlsx")
eq("the same string in an 'Amount' column of numbers becomes a NUMBER",
   [c["ref"] for c in num["coerced"]], ["B5"])
apply(b2, num)
ws = b2.sheet("Amts.xlsx")
eq("…on disk", [type(ws["B5"].value).__name__, ws["B5"].value], ["int", 2500])
b.drop()
b2.drop()


# ══════════════════════════════════════════════════════════════════════════════
# THE CROSS-LANGUAGE PIN — one rule, two implementations, no drift
#
# ⚠️ THIS TABLE IS THE SAME TABLE bridge/tests/test_office_ai.js WALKS IN JAVASCRIPT,
# value for value. Change an accepted shape in one language and this fails in the other.
# It is here rather than in a fixture file because a table nobody can see is a table
# nobody checks.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ the coercion table, pinned across both implementations ═══")
TABLE = [
    ("$2,500", 2500, "$#,##0"), ("$400", 400, "$#,##0"),
    ("$400.50", 400.5, "$#,##0.00"), ("$0.99", 0.99, "$#,##0.00"),
    ("-$5", -5, "$#,##0"), ("$-5", -5, "$#,##0"), ("$ 2,500", 2500, "$#,##0"),
    ("2,500", 2500, "#,##0"), ("1,234,567.89", 1234567.89, "#,##0.00"),
    ("50%", 0.5, "0%"), ("12.5%", 0.125, "0.0%"), ("-3%", -0.03, "0%"),
    ("1,000%", 10, "0%"), ("0%", 0, "0%"),
    ("1234", 1234, None), ("-12.5", -12.5, None), (".5", 0.5, None), ("0.5", 0.5, None),
]
REFUSED = ["007", "-007", "$007", "1e5", "0x10", "1,23", "12,3456", "(2,500)",
           "(555) 010-1234", "$2,500-B", "2500 kr", "2500 USD", "€1.234,56", "£5",
           "¥500", "1 234,56", "", "   ", "hello",
           "$1234567890123456789012345678901234"]
for src, val, pat in TABLE:
    got = oo.coerce_numeric(src)
    eq(f"coerce_numeric({src!r})", got and (got["v"], got["n"]), (val, pat))
for src in REFUSED:
    eq(f"coerce_numeric leaves {src!r} as TEXT", oo.coerce_numeric(src), None)
check("coerce_numeric is TOTAL — junk costs the coercion, never a throw",
      all((lambda v: (oo.coerce_numeric(v), True)[1])(v)
          for v in (None, 0, 1.5, True, [], {})))
check("EVERY non-$ currency and every non-US locale is refused, and that is a scope "
      "decision written down rather than an oversight: '€1.234,56' is 1234.56 in Germany "
      "and nonsense elsewhere, and guessing turns a thousands separator into a decimal "
      "point — a budget wrong by a factor of a thousand, silently",
      all(oo.coerce_numeric(s) is None for s in
          ("€1.234,56", "£5", "¥500", "CHF 5", "R$ 5", "5 kr", "1 234,56", "2 500")))

# The JS side of the table, read out of the page so the two cannot silently diverge.
PANEL = (ROOT / "bridge" / "panel" / "office.html").read_text()
for src, _v, _p in TABLE[:14]:
    check(f"the page's own test table carries {src!r} too",
          f"['{src}'," in (ROOT / "bridge" / "tests" / "test_office_ai.js").read_text())
check("the page implements the same four shapes under the same names",
      all(k in PANEL for k in ("CO_CURRENCY", "CO_THOUSANDS", "CO_PERCENT", "CO_PLAIN")))
check("…and the same intent overrides", "TEXT_MARK" in PANEL and "as_text" in PANEL)
check("…and the same inference weights",
      all(f"INFER_W_{k} = 2" in PANEL or f"INFER_W_{k} = 2," in PANEL
          for k in ("OP_COL", "SHEET_COL", "HEADER")))
eq("the weights themselves agree across the two languages",
   [oo.INFER_W_OP_COL, oo.INFER_W_SHEET_COL, oo.INFER_W_HEADER, oo.INFER_W_SHAPE],
   [2, 2, 2, 1])
for word in ("planned", "amount", "price"):
    check(f"the numeric header word {word!r} is in both word lists",
          word in oo.NUM_HEADER_WORDS and f"'{word}'" in PANEL)
for word in ("phone", "sku", "code"):
    check(f"the text header word {word!r} is in both word lists",
          word in oo.TEXT_HEADER_WORDS and f"'{word}'" in PANEL)


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY 6 — THE ADVERSARIAL CAMPAIGN'S OWN JOURNEYS (2026-08-28, batch fix)
#
# Every finding below reproduced against the LIVE stack on 2026-08-28 and has a repro in
# bridge/tests/test_office_adversarial.py under the same id. That file is the CAMPAIGN
# LEDGER and is deliberately not a gate (it exits 0 always). THIS is the gate: the
# journey-shaped ones are pinned here, forever, in the words of the user story they broke.
# ══════════════════════════════════════════════════════════════════════════════
print("\n═══ JOURNEY 6: the adversarial campaign — availability and consent ═══")

# ── F-18 · THE BRIDGE STOPPED ANSWERING ──────────────────────────────────────
# "add a sheet called <31 characters>" twice. `add_sheet`'s collision walk re-truncated
# the candidate back to the SAME 31 characters, so it could never find a free name — an
# INFINITE LOOP at 100% CPU, reached from BOTH stage_changes and apply_changeset, so the
# HTTP request never returned and a bridge worker thread was gone for the life of the
# process. Availability, not honesty: the worst class on this lane.
print("\n── F-18: a 31-character sheet name, twice ──")
b = Bench()
NAME31 = "x" * office.SHEET_NAME_MAX
wb = openpyxl.Workbook()
wb.active.title = "Data"
wb.create_sheet(NAME31)
wb.save(b.path("F18.xlsx"))
import signal as _sig
_hung = False
if hasattr(_sig, "SIGALRM"):
    def _boom(_s, _f):
        raise TimeoutError("hung")
    _old = _sig.signal(_sig.SIGALRM, _boom)
    _sig.setitimer(_sig.ITIMER_REAL, 5.0)
    try:
        res = stage(b, [{"op": "add_sheet", "name": NAME31}], name="F18.xlsx")
        got = apply(b, res)
    except TimeoutError:
        _hung = True
        res = got = None
    finally:
        _sig.setitimer(_sig.ITIMER_REAL, 0)
        _sig.signal(_sig.SIGALRM, _old)
check("F-18 · adding a sheet whose name is taken AND already 31 characters long RETURNS "
      "— it used to spin forever and burn a bridge thread permanently", not _hung)
if not _hung and got:
    names = openpyxl.load_workbook(b.path("F18.xlsx")).sheetnames
    check("…and the second sheet really exists, under a stepped name inside Excel's "
          "31-character limit", len(names) == 3 and all(len(n) <= 31 for n in names),
          names)
    check("…and the name it stepped to is DIFFERENT from the one that was taken",
          len(set(n.lower() for n in names)) == 3, names)
b.drop()

# ── F-19 · APPLY ANSWERED HTTP 500 AND ATE THE CHANGESET ─────────────────────
# "put this in A2 and add a sheet called Q1:Q2". `validate_ops` checked only LENGTH, so it
# staged happily; then openpyxl's `create_sheet` raised a bare ValueError for the colon,
# `save_doc` catches only OfficeError, and the route answered 500 WITH A TRACEBACK — after
# the checkpoint, the daily .bak and the pre-agent copy had all been taken, with the whole
# changeset (including the perfectly good `set`) lost and every retry crashing the same way.
print("\n── F-19: an Excel-invalid sheet name ──")
b = Bench()
wb = openpyxl.Workbook()
wb.active["A1"] = "important"
wb.save(b.path("F19.xlsx"))
_before = os.path.getmtime(b.path("F19.xlsx"))
res, err = oo.stage_changes(b.root, "journey", "F19.xlsx", None,
                            [{"op": "set", "at": "A2", "values": [["also mine"]]},
                             {"op": "add_sheet", "name": "Q1:Q2"}])
check("F-19 · a sheet name holding one of Excel's forbidden characters is REFUSED AT "
      "STAGING, before there is anything to approve", res is None and bool(err))
check("…and the refusal says which character and why, rather than being a traceback",
      ":" in str(err) and "Excel" in str(err), err)
check("…and NOTHING was touched: no checkpoint, no .bak, no pre-agent copy, and the "
      "workbook's own mtime did not move",
      not oo.list_checkpoints(b.root, "F19.xlsx")
      and os.path.getmtime(b.path("F19.xlsx")) == _before
      and sorted(os.listdir(os.path.dirname(b.path("F19.xlsx")))) == ["F19.xlsx"])
for bad in (":", "[", "]", "*", "?", "/", "\\"):
    r2, e2 = oo.stage_changes(b.root, "journey", "F19.xlsx", None,
                              [{"op": "add_sheet", "name": "A" + bad + "B"}])
    check(f"…and every one of Excel's seven is refused ({bad!r})", r2 is None and bool(e2))
# ⚠️ AND THE FLOOR UNDER IT: a snapshot that arrives from anywhere else must still not 500.
try:
    office.write_snapshot(
        {"id": "w", "sheetOrder": ["s"], "styles": {},
         "sheets": {"s": {"id": "s", "name": "Q1:Q2", "cellData": {}}}},
        b.path("never.xlsx"))
    _raised = "nothing"
except office.OfficeError as e:
    _raised = "OfficeError"
except Exception as e:                                           # noqa: BLE001
    _raised = type(e).__name__
eq("…and write_snapshot turns an unwritable title into an OfficeError, never a bare "
   "ValueError escaping to the route", _raised, "OfficeError")
b.drop()

# ── F-01 · APPLY OVER A FILE THAT MOVED SINCE THE PREVIEW ────────────────────
# Stage a change; something else writes the workbook (the editor's writeback, Debi's own
# save, another changeset); press Apply. It APPLIED, against a preview that was now
# fiction — the card had promised `A1: 10 → 50` and the receipt afterwards read "0 of 4
# re-read cell(s) hold what the change said they would". The dirty heartbeat does not
# cover this, because a SAVED writeback clears dirty. The UNDO path had this fence already.
print("\n── F-01: the apply's mtime fence ──")
b = Bench()
wb = openpyxl.Workbook()
for r, v in enumerate([10, 20, 30, 40], start=1):
    wb.active.cell(r, 1, v)
wb.save(b.path("F01.xlsx"))
res = stage(b, [{"op": "set", "at": "A1", "values": [[50], [60], [70], [80]]}],
            name="F01.xlsx")
eq("the card promises the four cells", res["cells_changed"], 4)
# Somebody else writes the file between the preview and the press.
import time as _t
_t.sleep(0.01)
wb2 = openpyxl.load_workbook(b.path("F01.xlsx"))
wb2.active["A1"] = 999
wb2.save(b.path("F01.xlsx"))
got, err = oo.apply_changeset(b.root, res["changeset_id"])
check("F-01 · Apply REFUSES when the workbook changed since the preview was computed",
      got is None and bool(err))
check("…in a sentence that says the preview is out of date and that nothing was applied",
      "out of date" in str(err) and "Nothing was applied" in str(err), err)
eq("…and the other writer's value is still there — the refusal wrote nothing",
   b.sheet("F01.xlsx")["A1"].value, 999)
check("…and the proposal is still pending, so re-staging is the way forward rather than "
      "a lost changeset", oo.get_changeset(res["changeset_id"]) is not None)
# The same fence must NOT fire on an untouched file: a guard that always refuses is the
# same as no guard.
res2 = stage(b, [{"op": "set", "at": "B1", "values": [["ok"]]}], name="F01.xlsx")
got2, err2 = oo.apply_changeset(b.root, res2["changeset_id"])
check("…and it does NOT fire on a workbook nobody touched", got2 is not None, err2)
b.drop()

# ── F-20 · TEN REFUSED PRESSES DESTROYED THE UNDO STACK ──────────────────────
# `apply_changeset` pushed the checkpoint BEFORE `_apply` ran the dirty check, so each
# REFUSED press ("you have unsaved edits…") added a checkpoint of an UNCHANGED file — and
# CHECKPOINT_KEEP is 10. Measured: 3 real applies then 10 refused presses left 10
# checkpoints, NONE of them from a real apply. The undo stack was destroyed by gestures
# that changed nothing.
print("\n── F-20: a refused Apply must not touch anything ──")
b = Bench()
wb = openpyxl.Workbook()
wb.active["A1"] = "v0"
wb.save(b.path("F20.xlsx"))
real = []
for i in range(3):
    r = stage(b, [{"op": "set", "at": "A1", "values": [[f"v{i + 1}"]]}], name="F20.xlsx")
    apply(b, r)
    real.append(r["changeset_id"])
eq("three real applies leave three checkpoints",
   len(oo.list_checkpoints(b.root, "F20.xlsx")), 3)
oo.heartbeat("F20.xlsx", True)                 # the page now holds unsaved edits
_refused = 0
for i in range(10):
    r = stage(b, [{"op": "set", "at": "A1", "values": [[f"x{i}"]]}], name="F20.xlsx")
    got, err = oo.apply_changeset(b.root, r["changeset_id"])
    if got is None:
        _refused += 1
eq("…ten presses while the editor is dirty are all refused", _refused, 10)
stack = [e["changeset_id"] for e in oo.list_checkpoints(b.root, "F20.xlsx")]
eq("F-20 · and NOT ONE of them added a checkpoint — the three real undo points survive",
   sorted(stack), sorted(real))
eq("…and the workbook still holds the last real apply", b.sheet("F20.xlsx")["A1"].value,
   "v3")
oo.heartbeat_clear()
b.drop()

# ── F-03 · A WIDE SHEET WAS CORRUPTED, PERMANENTLY, IN THE SAVED FILE ────────
# `rc_apply` remapped only the first TIER1_MAX_COLS (200) columns — the PAGE'S RENDER
# WINDOW, used as the width of the cell mover. On a sheet 250 columns wide a ROW INSERT
# shifted A…GR down one and left GS…IP where they were, splitting the header row across
# two different rows permanently; a COLUMN INSERT destroyed the value in column 200. The
# only note that fired claimed one column had "fallen off the edge" — false on three
# counts, and it fired for row inserts where no column moved at all.
print("\n── F-03: insert and delete on a sheet wider than the render window ──")
b = Bench()
WIDE = 250
wb = openpyxl.Workbook()
for c in range(1, WIDE + 1):
    wb.active.cell(1, c, f"h{c}")
    wb.active.cell(2, c, c)
wb.save(b.path("F03.xlsx"))
res = stage(b, [{"op": "insert", "what": "row", "at": "1"}], name="F03.xlsx")
apply(b, res)
ws = b.sheet("F03.xlsx")
check("F-03 · a ROW INSERT moves the WHOLE used width, not the first 200 columns — the "
      "header row is one row, all the way across",
      all(ws.cell(2, c).value == f"h{c}" for c in range(1, WIDE + 1)),
      [ws.cell(2, c).value for c in (199, 200, 201, 250)])
check("…and the new row is blank all the way across too",
      all(ws.cell(1, c).value is None for c in range(1, WIDE + 1)))
check("…and no note claims a column fell off an edge nothing reached",
      not any("fell off" in n for n in res["notes"]), res["notes"])
b2 = Bench()
wb = openpyxl.Workbook()
for c in range(1, WIDE + 1):
    wb.active.cell(1, c, c)
wb.save(b2.path("F03c.xlsx"))
res = stage(b2, [{"op": "insert", "what": "col", "at": "A"}], name="F03c.xlsx")
apply(b2, res)
ws = b2.sheet("F03c.xlsx")
check("…and a COLUMN INSERT shifts every column right instead of destroying the one at "
      "the old cap", ws.cell(1, 1).value is None
      and all(ws.cell(1, c + 1).value == c for c in range(1, WIDE + 1)),
      [ws.cell(1, c).value for c in (1, 200, 201, 251)])
b2.drop()
# ── F-03b: and the note, when it can fire at all, names the gesture that happened ──
res = stage(b, [{"op": "delete_rc", "what": "row", "at": "1"}], name="F03.xlsx")
check("F-03b · a DELETE never gets a note that starts \"the insert reached\"",
      not any(n.startswith("the insert reached") for n in res["notes"]), res["notes"])
b.drop()

# ── F-07 / F-22 · THE SAFETY COPY DESTROYED A REAL WORKBOOK ──────────────────
# `pre_agent_for` returned the SIBLING `<stem>.pre-agent.xlsx`, and `op_list` listed such
# files as ordinary workbooks — so Debi could make one from the panel. The first apply on
# `report.xlsx` then silently overwrote her `report.pre-agent.xlsx`, and nothing on the
# card, in the receipt or in the notes named the file it was about to destroy (F-07). And a
# workbook actually named that could never be written at all: the copy resolved to ITSELF
# and the refusal was a raw shutil.SameFileError with two absolute temp paths in it (F-22).
print("\n── F-07 / F-22: the pre-agent copy, namespaced ──")
b = Bench()
wb = openpyxl.Workbook()
wb.active["A1"] = "main"
wb.save(b.path("Report.xlsx"))
wb = openpyxl.Workbook()
wb.active["A1"] = "MY REAL DATA"                 # a workbook Debi actually has
wb.save(b.path("Report.pre-agent.xlsx"))
res = stage(b, [{"op": "set", "at": "A1", "values": [["changed"]]}], name="Report.xlsx")
got = apply(b, res)
eq("F-07 · Debi's own Report.pre-agent.xlsx is UNTOUCHED by an apply on Report.xlsx",
   b.sheet("Report.pre-agent.xlsx")["A1"].value, "MY REAL DATA")
check("…because the copy is namespaced under .checkpoints/<stem>/ instead of living in "
      "the namespace of real documents",
      got["pre_agent_copy"].startswith(office.CHECKPOINT_DIR + "/")
      and os.path.isfile(oo.pre_agent_for(b.path("Report.xlsx"))))
eq("…and it holds what the workbook said BEFORE the write, which is the whole point of it",
   openpyxl.load_workbook(oo.pre_agent_for(b.path("Report.xlsx"))).active["A1"].value,
   "main")
check("…and the receipt NAMES the copy it took, so an undo is a question with an answer",
      any(got["pre_agent_copy"] in n for n in got["notes"]))
# F-22: and that workbook can now be written like any other.
res = stage(b, [{"op": "set", "at": "A2", "values": [["fine"]]}],
            name="Report.pre-agent.xlsx")
got2, err2 = oo.apply_changeset(b.root, res["changeset_id"])
check("F-22 · a workbook named *.pre-agent.xlsx can be written, instead of answering a "
      "raw shutil.SameFileError with two temp paths in it", got2 is not None, err2)
eq("…and its own copy goes to its own folder, not onto itself",
   oo.pre_agent_label(b.path("Report.pre-agent.xlsx")),
   office.CHECKPOINT_DIR + "/Report.pre-agent/pre-agent.xlsx")
# C4: and neither copy is listed as a workbook Debi could open.
listed = [f["name"] for f in oo.op_list(b.root)["files"]]
check("C4 · a safety copy is not listed as an ordinary workbook, exactly as a .bak is "
      "not — it has no size, no date and no delete link of its own in the rail",
      "Report.pre-agent.xlsx" not in listed and "Report.xlsx" in listed, listed)
b.drop()

# ── F-21 · A RENAME KILLED UNDO FOR GOOD ─────────────────────────────────────
# `checkpoint_dir` is keyed by the file STEM, and `rename_doc` moved neither the stack nor
# the pre-agent sibling. After a rename `undo_changeset` answered "no such workbook" —
# blaming a missing file for what was really an orphaned stack — while the checkpoint sat
# on disk under the old stem, unreachable for ever.
print("\n── F-21: undo after a rename ──")
b = Bench()
wb = openpyxl.Workbook()
wb.active["A1"] = "orig"
wb.save(b.path("F21.xlsx"))
res = stage(b, [{"op": "set", "at": "A1", "values": [["new"]]}], name="F21.xlsx")
apply(b, res)
eq("the apply landed", b.sheet("F21.xlsx")["A1"].value, "new")
new_name, err = office.rename_doc(b.root, "F21.xlsx", "F21 renamed.xlsx")
check("the rename succeeded", new_name == "F21 renamed.xlsx", err)
check("F-21 · the checkpoint stack MOVED with the file, so it is reachable under the new "
      "name", bool(oo.list_checkpoints(b.root, "F21 renamed.xlsx"))
      and not oo.list_checkpoints(b.root, "F21.xlsx"))
got, err = oo.undo_changeset(b.root, res["changeset_id"])
check("…and 'Undo this change' still works after a rename, instead of answering 'no such "
      "workbook' about a file that is right there", got is not None, err)
eq("…and it really restored the pre-apply content",
   b.sheet("F21 renamed.xlsx")["A1"].value, "orig")
b.drop()

# ── F-02 · THE CARD NAMED A SHEET THAT WAS NOT GOING TO BE WRITTEN ───────────
# `public_changeset` returned the REQUESTED sheet name while `target_sid` falls back to
# the first sheet for an unknown one — so staging against "Q3 Data" on a workbook of
# Alpha/Beta/Gamma produced a card headed `sheet: "Q3 Data"` whose every preview row said
# `Alpha`, with no note. The honest sentence existed and reached the APPLY result only,
# i.e. after the write, on a surface whose whole job is consent BEFORE it.
print("\n── F-02: the card names the sheet that will be written ──")
b = Bench()
wb = openpyxl.Workbook()
wb.active.title = "Alpha"
wb.create_sheet("Beta")
wb.create_sheet("Gamma")
wb.save(b.path("F02.xlsx"))
res = stage(b, [{"op": "set", "at": "A1", "values": [["x"]]}], name="F02.xlsx",
            sheet="Q3 Data")
eq("F-02 · the card is headed with the sheet that will ACTUALLY be written",
   res["sheet"], "Alpha")
eq("…and it still carries what the model ASKED for, so the two can be compared",
   res["sheet_asked"], "Q3 Data")
check("…and a note on the CARD — before Apply — says the named sheet does not exist",
      any("no sheet called 'Q3 Data'" in n for n in res["notes"]), res["notes"])
check("…and every preview row agrees with the heading",
      all(p["sheet"] == "Alpha" for p in res["preview"]), res["preview"])
# The negative path: a sheet that DOES exist gets no warning and is named as itself.
res = stage(b, [{"op": "set", "at": "A1", "values": [["y"]]}], name="F02.xlsx",
            sheet="beta")
eq("…and a sheet that exists is named as itself", res["sheet"], "Beta")
check("…with no warning, because there is nothing to warn about",
      not any("no sheet called" in n for n in res["notes"]))
b.drop()

# ── F-05 / F-06 / F-23 · THE RECEIPT'S "0 OF 0" GREEN BADGE ──────────────────
# Three shapes of change that the consent surface could not see at all, because
# `snapshot_diff` walks cell VALUES: a formatting-only change ("5 formatted — 0 cells
# would change", receipt "0 of 0 re-read cell(s)", and A1 really WAS bold on red), a
# change that only reshapes a merge, and a sheet add or rename. The panel's success badge
# renders from those numbers.
print("\n── F-05 / F-06 / F-23: formatting, merges and sheets on the card ──")
b = Bench()
wb = openpyxl.Workbook()
for r in range(1, 6):
    wb.active.cell(r, 1, r)
wb.save(b.path("F06.xlsx"))
res = stage(b, [{"op": "style", "at": "A1:A5", "set": {"bl": 1, "bg": "#ff0000"}}],
            name="F06.xlsx")
eq("F-06 · a formatting-only change has five FORMATTING before → after rows on the card",
   res["style_total"], 5)
check("…each naming what the cell said before and what it will say after",
      res["style_preview"][0]["before"] == "(none)"
      and "bold" in res["style_preview"][0]["after"], res["style_preview"][:1])
check("…and the card's first line no longer ends '0 cells would change' with nothing "
      "after it", "FORMATTING only" in res["summary"], res["summary"])
got = apply(b, res)
check("…and the RECEIPT re-read them from disk, rather than verifying nothing and "
      "printing a green 0 of 0",
      [v for v in got["verify"] if v.get("kind") == "format"]
      and all(v["match"] for v in got["verify"]), got["verify_note"])
check("…and the write really happened", b.sheet("F06.xlsx")["A1"].font.bold is True)
b.drop()
b = Bench()
wb = openpyxl.Workbook()
wb.active["A1"] = "t"
wb.active.merge_cells("A1:A4")
wb.save(b.path("F05.xlsx"))
res = stage(b, [{"op": "delete_rc", "what": "row", "at": "2", "n": 2}], name="F05.xlsx")
eq("F-05 · a change that reshapes a merge says so, with the before → after range",
   [(m["before"], m["after"]) for m in res["merge_changes"]], [("A1:A4", "A1:A2")])
check("…and the card's first line counts it, so the number cannot contradict the clause "
      "before it", "merged range" in res["summary"], res["summary"])
apply(b, res)
eq("…and the file agrees with what the card said",
   [str(m) for m in openpyxl.load_workbook(b.path("F05.xlsx")).active.merged_cells.ranges],
   ["A1:A2"])
b.drop()
b = Bench()
wb = openpyxl.Workbook()
wb.create_sheet("Data")
wb.save(b.path("F23.xlsx"))
res = stage(b, [{"op": "add_sheet", "name": "Data"}], name="F23.xlsx")
got = apply(b, res)
_srows = [v for v in got["verify"] if v.get("kind") == "sheet"]
check("F-23 · a sheet-add changeset VERIFIES the sheet, from a re-read of the workbook",
      _srows and all(v["match"] for v in _srows), got["verify"])
check("…and the receipt's sentence is about what it actually read, not '0 of 0 re-read "
      "cell(s)'", "sheet(s)" in got["verify_note"], got["verify_note"])
eq("…and the collision stepped, as it always did", got["sheets_added"], ["Data 2"])
b.drop()

# ── F-27 · DATA DEBI HID CAME BACK ON SCREEN ─────────────────────────────────
# Freeze panes, gridline visibility, hidden rows, hidden columns and autofilter were lost
# by every apply — and `sheet_snapshot` emitted HARD-CODED freeze/showGridlines/hd values,
# read from nothing and written to nothing, so the snapshot ASSERTED "not frozen, gridlines
# on, nothing hidden" about a sheet where all three were false. A present-but-fake field is
# worse than an absent one, and a hidden column reappearing is data she deliberately hid.
print("\n── F-27: the four things the round-trip did not carry ──")
b = Bench()
wb = openpyxl.Workbook()
ws = wb.active
for r in range(1, 11):
    for c in range(1, 6):
        ws.cell(r, c, r * c)
ws.freeze_panes = "B2"
ws.sheet_view.showGridLines = False
ws.column_dimensions["D"].hidden = True
ws.row_dimensions[11].hidden = True
ws.auto_filter.ref = "A1:E10"
wb.save(b.path("F27.xlsx"))
snap = office.snapshot_from_path(b.path("F27.xlsx"))
sh = snap["sheets"][snap["sheetOrder"][0]]
eq("F-27 · the snapshot READS the freeze rather than asserting there is none",
   (sh["freeze"]["xSplit"], sh["freeze"]["ySplit"]), (1, 1))
eq("…and the gridline flag rather than always saying 1", sh["showGridlines"], 0)
eq("…and the autofilter, which it had no field for at all", sh["autoFilter"], "A1:E10")
eq("…and hd on the column Debi hid, rather than 0 on every column",
   sh["columnData"]["3"]["hd"], 1)
eq("…and on the row she hid", sh["rowData"]["10"]["hd"], 1)
res = stage(b, [{"op": "set", "at": "A1", "values": [["poke"]]}], name="F27.xlsx")
apply(b, res)
ws2 = b.sheet("F27.xlsx")
eq("…and all five SURVIVE an apply, instead of the hidden column coming back on screen",
   (ws2.freeze_panes, ws2.sheet_view.showGridLines,
    ws2.column_dimensions["D"].hidden, ws2.row_dimensions[11].hidden,
    ws2.auto_filter.ref),
   ("B2", False, True, True, "A1:E10"))
check("…and the fidelity sentence for THIS save path no longer claims to lose them",
      all(x in office.FIDELITY_NOTE
          for x in ("freeze panes", "hidden rows and columns", "autofilter")))
b.drop()

# ── F-09 / F-10 · TWO TYPE LIES THE COERCION RULE COULD STILL TELL ───────────
# F-09: a column Debi formatted `@` MEANS "this is text", and "1,200" was stored as the
# NUMBER 1200 with `#,##0` — her own stated intent overridden, and a cell formatted
# `0.00" kg"` lost her unit pattern the same way, under a note that said the value had
# gained "a matching format" and never said what went.
# F-10: "2026-01-15" written into a cell formatted `yyyy-mm-dd` KEEPS the format, so it
# renders IDENTICALLY to the real dates above it while being a string that breaks =A3-A1
# and every date sort. The card printed the raw serial, so the row read "46034 →
# 2026-01-15" — which looks like a FIX. This is the $2,500 incident with the tell removed.
print("\n── F-09 / F-10: an explicit format is an instruction ──")
import datetime as _dt
b = Bench()
wb = openpyxl.Workbook()
ws = wb.active
ws.cell(1, 1).number_format = "@"
ws.cell(2, 1, 5).number_format = '0.00" kg"'
ws.cell(1, 3, _dt.date(2026, 1, 10))
ws.cell(2, 3, _dt.date(2026, 1, 11))
ws.cell(3, 3, _dt.date(2026, 1, 12))
wb.save(b.path("F09.xlsx"))
res = stage(b, [{"op": "set", "at": "A1", "values": [["1,200"], ["1,200"]]},
                {"op": "set", "at": "C3", "values": [["2026-01-15"]]}],
            name="F09.xlsx")
apply(b, res)
ws = b.sheet("F09.xlsx")
check("F-09 · a cell formatted `@` keeps the text it was given — an explicit text format "
      "outranks the inference, the way the apostrophe and as_text do",
      isinstance(ws["A1"].value, str) and ws["A1"].value == "1,200",
      (ws["A1"].value, type(ws["A1"].value).__name__))
check("…and the card SAYS it was kept as text, and why",
      any("formatted as text (@)" in n for n in res["notes"]), res["notes"])
check("…and when a coercion DOES replace a pattern, the card names the pattern it "
      "replaced", any('0.00" kg"' in n for n in res["notes"]), res["notes"])
check("F-10 · a value that stays TEXT in a DATE-formatted cell is flagged, the way a "
      "currency coercion is", any("DATE" in n and "break every date" in n
                                  for n in res["notes"]), res["notes"])
_c = [p for p in res["preview"] if p["ref"] == "C3"]
check("…and the card's before column renders the date, not the raw serial — '46034 → "
      "2026-01-15' read like a FIX",
      _c and _c[0]["before_display"].startswith("2026-01-12"), _c)
b.drop()


# ══════════════════════════════════════════════════════════════════════════════
# JOURNEY — A DOCUMENT AND A PRESENTATION, END TO END (loffice-2026-08-29a, stage 3)
#
# THE USER STORY: Debi presses "Blank document" (or "Blank presentation"), the editor
# opens it, she types, she saves, she comes back later and her words are still there.
#
# ⚠️ WHAT THIS TEST CAN AND CANNOT BE. The middle of that story is a WebAssembly editor
# in a WKWebView, and this file must stay model-free and browser-free (see the header).
# So the EDITOR'S STEP IS PLAYED BY REAL BYTES OF OUR OWN MAKING: the package that comes
# back from `officeblank` with one part rewritten, which is exactly the shape the editor
# posts to /api/office/writeback (a complete OOXML package, ours to store verbatim).
# That makes every step this codebase owns executable forever:
#     create → read back → the editor's write-back → read back again → the text is there
# and it makes the two things the bridge could get wrong impossible to regress: storing
# the wrong bytes, and mis-typing the file on the way through.
#
# The EDITOR half was walked live in a real WKWebView for this slice — a blank .docx and
# a blank .pptx created here, opened in the vendored editor, typed into through the
# editor's own document API, saved through this very write-back, and reopened with the
# text read back out of the reopened editor. That evidence is a screenshot in the ship
# report, which is where the doctrine puts it; this is the part that runs every time.
# ══════════════════════════════════════════════════════════════════════════════
import io as _io                                                  # noqa: E402
import zipfile as _zip                                            # noqa: E402

import officeblank as _blank                                      # noqa: E402
import oo as _oomod                                               # noqa: E402


def _edit_package(data, part, marker):
    """The editor's step, played honestly: the same package with `marker` in one part.

    Rebuilt member by member (a zip cannot be edited in place), which also proves the
    write-back stores WHATEVER complete package it is handed rather than re-deriving it.
    """
    src = _zip.ZipFile(_io.BytesIO(data))
    out = _io.BytesIO()
    with _zip.ZipFile(out, "w", _zip.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            if info.filename == part:
                body = body.replace(b"<w:p/>", b"<w:p><w:r><w:t>" + marker
                                    + b"</w:t></w:r></w:p>")
                body = body.replace(b"<p:cSld>", b"<p:cSld><!--" + marker + b"-->")
            dst.writestr(info.filename, body)
    return out.getvalue()


for _kind, _ext, _part, _marker in (
        ("document", ".docx", "word/document.xml", b"JOURNEY-DOCX-TEXT"),
        ("presentation", ".pptx", "ppt/slides/slide1.xml", b"JOURNEY-PPTX-TEXT")):
    b = Bench()
    # 1 ─ the card is pressed: a blank file of that type, made by us, never vendored
    _name, _why = office.create_doc(b.root, "Notes", _ext)
    eq(f"a blank {_kind} is created", _name, "Notes" + _ext)
    check(f"…and it is on disk as a real package",
          office.verify_package(open(b.path(_name), "rb").read(), _ext) is None, _why)
    # it must be visible in the list, with its kind, or the rail cannot show it
    _row = [r for r in office.list_docs(b.root) if r["name"] == _name][0]
    eq(f"…and the list calls it what it is", _row["kind"],
       {"document": "doc", "presentation": "slides"}[_kind])

    # 2 ─ LOffice hands the bytes to the editor through /api/office/download's target
    _served, _why = office.doc_target(b.root, _name)
    check(f"…and the {_kind} is servable to the editor", bool(_served), _why)
    _bytes = open(_served, "rb").read()

    # 3 ─ THE EDITOR'S STEP: the user types, the editor serialises the whole package
    _edited = _edit_package(_bytes, _part, _marker)
    check(f"the edited {_kind} is still a valid package",
          office.verify_package(_edited, _ext) is None)

    # 4 ─ ⌘S: the write-back, with the mtime fence the editor passes
    _mtime = os.stat(_served).st_mtime
    _rep, _err = _oomod.writeback(office, b.root, _name, _edited, _mtime)
    check(f"the {_kind} write-back landed", _rep is not None, _err)
    check("…and it took the daily safety copy, with the right extension",
          _rep and _rep["backup"].endswith(".bak" + _ext), _rep)
    # THE FENCE IS REAL FOR THESE TYPES TOO: a save that thinks the file is older than
    # it is must be REFUSED rather than silently winning. `- 5` rather than the mtime
    # this test just read, because the fence deliberately allows one second of slack
    # (the wire carries a float through JSON and a filesystem whose timestamp
    # resolution is not ours to assume) and a same-second re-save is inside it.
    _rep2, _err2 = _oomod.writeback(office, b.root, _name, _edited, _mtime - 5)
    check("…and a save against a STALE mtime is refused, not silently won",
          _rep2 is None and _err2[0] == 409, _err2)
    check("…with a sentence that says the file changed and what to do",
          _rep2 is None and "changed on disk" in _err2[1], _err2)
    _rep3, _err3 = _oomod.writeback(office, b.root, _name, _edited, _mtime - 5, True)
    check("…and `force` overrides it, because a refusal nobody can override is its own "
          "kind of data loss", _rep3 is not None, _err3)

    # 5 ─ SHE COMES BACK: reopen means read the bytes off disk again
    _again = open(b.path(_name), "rb").read()
    _z = _zip.ZipFile(_io.BytesIO(_again))
    check(f"reopening the {_kind} shows the edit — the marker is in {_part}",
          _marker in _z.read(_part))
    check("…and the package is intact, not merely present",
          _z.testzip() is None and "[Content_Types].xml" in _z.namelist())
    eq("…and it is still the same file, under the same name",
       [r["name"] for r in office.list_docs(b.root) if r["name"] == _name], [_name])

    # 6 ─ AND NOTHING ELSE IN LOFFICE PRETENDS TO UNDERSTAND IT
    check(f"the snapshot mapper refuses the {_kind}",
          office.open_doc(b.root, _name)[0] is None)
    check(f"…the agent's read tool refuses it, with a sentence",
          oo.op_read(b.root, _name)[0] is None
          and _kind in (oo.op_read(b.root, _name)[1] or ""))
    check("…and a changeset cannot be staged against it",
          oo.stage_changes(b.root, "j", _name, None,
                           [{"op": "set", "at": "A1", "values": [["x"]]}])[0] is None)
    b.drop()


# ══ report ════════════════════════════════════════════════════════════════════
print("")
if FAIL:
    print(f"{len(FAIL)} FAILED (of {PASS + len(FAIL)}):")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print(f"office golden journeys OK — {PASS} checks passed")
