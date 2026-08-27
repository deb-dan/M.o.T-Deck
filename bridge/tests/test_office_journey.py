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


# ══ report ════════════════════════════════════════════════════════════════════
print("")
if FAIL:
    print(f"{len(FAIL)} FAILED (of {PASS + len(FAIL)}):")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print(f"office golden journeys OK — {PASS} checks passed")
