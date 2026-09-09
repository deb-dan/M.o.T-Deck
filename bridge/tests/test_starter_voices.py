"""Unit tests for the VCTK-13 starter voice set (bridge/voice.py + the endpoint).

The network half CANNOT be exercised here — the sandbox has no route to the HF
datasets-server and the signed asset URLs expire anyway. So everything that CAN be
made pure is: the binary search that locates a speaker's rows takes an INJECTED
probe, the row picker is a pure function over a page of JSON, and the ffmpeg command
line is built by a pure function. What is left un-tested is exactly the HTTP calls,
and that is stated in the endpoint's own docstring rather than papered over.

What is pinned:

  * the 13-slot table — the research's picks, the hard exclusions (p315, p280), and
    that no slot collides with another on disk.
  * starter_clip_name / starter_dir / the manifest round-trip.
  * vctk_speaker_bounds — the full binary-search decision table against a synthetic
    speaker-ordered column, including "not present" and "probe failed" AS DIFFERENT
    OUTCOMES, and the `s5` row that live-probing found sitting last.
  * THE 2026-08-14 REGRESSION, reproduced: walking the slot table in accent order while
    carrying a monotonic `lo` floor finds only a handful of thirteen present speakers
    (that was sample's "2 added — 11 failed"); walking starter_fetch_order() finds all
    thirteen. Both directions are asserted, so the fix cannot quietly rot.
  * starter_candidates — the research's accent-slot alternates, and the junk table.
  * the persisted offset index and starter_present (the re-run skip, .flac included).
  * the CLIP LENGTH GUARD: exact wav-header duration math, the ⚠️ size heuristic for
    non-wav, and the full ok / trim / warn / refuse verdict table.
  * vctk_pick_utterances — mic1 only, right speaker only, and total against every
    shape of surprise JSON.
  * ffmpeg_concat_argv.
  * CONTAINMENT: a starter clip is listed by library_entries but is NOT reachable
    through library_target — the delete endpoint's boundary is unchanged, so the
    starter set has no delete path at all (it is one button from being re-fetched).
  * starter_ref_text — ground truth in, ground truth out; nothing outside the starter
    dir can borrow a transcript.
  * the attribution text is present and non-empty (CC BY is only satisfied when the
    credit is actually rendered).

Run: python3 bridge/tests/test_starter_voices.py   (from repo root)
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

# ⚠️ THE APP LAYER IS NO LONGER ONE FILE (router/core split, 2026-08-28).
# bridge/app.py is a FACADE over bridge/core/*.py + bridge/routers/*.py, so the
# source-text assertions below read bridge/appsrc.py's assembled view of the whole
# app layer instead of one file. Read bridge/appsrc.py's header for why the
# assertions are source-text in the first place and why order is part of it.
from bridge.appsrc import APP_SOURCE as _APP_SOURCE            # noqa: E402
from bridge import voice                                        # noqa: E402

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# ── the table ────────────────────────────────────────────────────────────────
print("\nthe 13-slot table")
V = voice.STARTER_VOICES
check("thirteen slots, as specified", len(V) == 13)
check("every slot id is unique", len({s["slot"] for s in V}) == 13)
check("every speaker is unique", len({s["speaker"] for s in V}) == 13)
check("no two slots would write the same file",
      len({voice.starter_clip_name(s["slot"], s["speaker"]) for s in V}) == 13)
check("p315 is excluded — its transcripts were lost to a disk error, so no ground-"
      "truth ref_text is possible for it",
      "p315" not in {s["speaker"] for s in V})
check("p280 is excluded — accent 'Unknown', mic2 missing",
      "p280" not in {s["speaker"] for s in V})
check("the accent slots the research asked for are all filled",
      {"American", "English", "Irish", "Scottish", "Indian"}
      <= {s["accent"] for s in V})
check("five American and five English speakers (the us-*/uk-* slots)",
      sum(1 for s in V if s["accent"] == "American") == 5
      and sum(1 for s in V if s["accent"] == "English") == 5)
check("every entry carries the keys the manifest writes",
      all({"slot", "speaker", "sex", "accent", "region"} <= set(s) for s in V))
check("every speaker id looks like a VCTK id (pNNN)",
      all(s["speaker"][0] == "p" and s["speaker"][1:].isdigit() for s in V))

# ── names + paths ────────────────────────────────────────────────────────────
print("\nnames and paths")
check("a clip name carries the slot AND the speaker (the speaker id is the "
      "attribution handle and must stay visible in the chip)",
      voice.starter_clip_name("us-m-1", "p311") == "us-m-1-p311.wav")
check("the name is a bare basename — nothing that could climb a directory",
      "/" not in voice.starter_clip_name("us-m-1", "p311")
      and ".." not in voice.starter_clip_name("us-m-1", "p311"))
check("its suffix is one the engine can actually read",
      voice.normalize_ref_suffix(voice.starter_clip_name("a", "b")) == "wav")
check("the starter dir is INSIDE the voice library, one level down",
      voice.starter_dir("/r") == os.path.join(voice.voices_dir("/r"), "starter"))
check("the manifest lives beside the clips",
      voice.starter_manifest_path("/r")
      == os.path.join(voice.starter_dir("/r"), "starter.json"))

# ── vctk_speaker_bounds ──────────────────────────────────────────────────────
print("\nvctk_speaker_bounds (the binary search)")
# A synthetic speaker-ordered column: 4 speakers × 10 rows.
COL = (["p225"] * 10) + (["p226"] * 10) + (["p300"] * 10) + (["p376"] * 10)


def probe(i, calls=None):
    if calls is not None:
        calls.append(i)
    return COL[i] if 0 <= i < len(COL) else None


check("the FIRST row of the first speaker is found",
      voice.vctk_speaker_bounds("p225", probe, len(COL)) == 0)
check("a middle speaker lands on its FIRST row, not just any of its rows",
      voice.vctk_speaker_bounds("p300", probe, len(COL)) == 20)
check("the last speaker is found", voice.vctk_speaker_bounds("p376", probe, len(COL)) == 30)
check("a speaker that is not in the mirror returns None, not a wrong offset",
      voice.vctk_speaker_bounds("p999", probe, len(COL)) is None)
check("a speaker between two present ones returns None (lower_bound must not "
      "silently hand back the NEXT speaker's rows)",
      voice.vctk_speaker_bounds("p250", probe, len(COL)) is None)
# ⚠️ THE BUG OF 2026-08-14, HALF TWO. This used to assert `is None` — i.e. a probe that
# could not answer produced the SAME result as a speaker that is not in the mirror. On
# sample's Mac that turned one rate-limited request into "speaker not found in the dataset
# mirror", which was false (a live probe found all thirteen present) and pointed away
# from the only real remedy. The two outcomes are now different types.
try:
    voice.vctk_speaker_bounds("p300", lambda i: None, len(COL))
    _raised = False
except voice.VctkProbeUnavailable:
    _raised = True
check("a probe that CANNOT ANSWER raises VctkProbeUnavailable — it must never be "
      "reported as 'the speaker is absent'", _raised)
check("...and a speaker that really is absent still returns None, so the two failures "
      "stay distinguishable",
      voice.vctk_speaker_bounds("p250", probe, len(COL)) is None)
check("an empty speaker id is refused", voice.vctk_speaker_bounds("", probe, len(COL)) is None)
check("a zero/negative total is refused",
      voice.vctk_speaker_bounds("p225", probe, 0) is None
      and voice.vctk_speaker_bounds("p225", probe, -1) is None)
check("a `lo` floor narrows the search (the speakers are ascending, so the next one "
      "is never earlier than the last)",
      voice.vctk_speaker_bounds("p300", probe, len(COL), 20) == 20)
check("a `lo` floor PAST the answer cannot resurrect it",
      voice.vctk_speaker_bounds("p225", probe, len(COL), 20) is None)
calls = []
voice.vctk_speaker_bounds("p300", lambda i: probe(i, calls), len(COL))
check("the search is logarithmic, not a scan (this is what keeps the fetch inside "
      f"the datasets-server's rate limit) — {len(calls)} probes for 40 rows",
      len(calls) <= 8)
check("the real dataset's row count is the API-verified one",
      voice.VCTK_ROWS_TOTAL == 88156)
# Live-probed 2026-08-14: offset 88155 (the LAST row) is speaker `s5`, the one non-`p`
# id in VCTK. It sorts after every pNNN under a string compare ('s' > 'p'), which is
# exactly where it has to be for the ordering assumption to hold — pinned so a mirror
# that ever moved it would trip here rather than silently corrupt a search.
COL_S5 = COL + (["s5"] * 4)


def probe_s5(i):
    return COL_S5[i] if 0 <= i < len(COL_S5) else None


check("`s5` (the dataset's one non-pNNN speaker, live-observed as the LAST row) sorts "
      "after every pNNN, so the string ordering the search relies on holds end to end",
      "s5" > "p376"
      and voice.vctk_speaker_bounds("s5", probe_s5, len(COL_S5)) == len(COL)
      and voice.vctk_speaker_bounds("p376", probe_s5, len(COL_S5)) == 30)

# ── the walk order (THE BUG of 2026-08-14, half one) ─────────────────────────
print("\nstarter_fetch_order — the 'lo' floor is only sound in speaker order")
ORDER = voice.starter_fetch_order()
check("the fetch walks the slots in ASCENDING SPEAKER order",
      [s["speaker"] for s in ORDER] == sorted(s["speaker"] for s in voice.STARTER_VOICES))
check("it keeps every slot — sorting the WALK must not drop or duplicate a slot",
      len(ORDER) == len(voice.STARTER_VOICES)
      and {s["slot"] for s in ORDER} == {s["slot"] for s in voice.STARTER_VOICES})
check("the TABLE itself is untouched — it is ordered by accent slot because that is "
      "the order the picker reads in",
      voice.STARTER_VOICES[0]["slot"] == "us-m-1"
      and voice.STARTER_VOICES[0]["speaker"] == "p311")
check("the shipped table is NOT already speaker-sorted — i.e. this fix is doing real "
      "work, which is precisely why the naive walk failed",
      [s["speaker"] for s in voice.STARTER_VOICES]
      != sorted(s["speaker"] for s in voice.STARTER_VOICES))

# THE REGRESSION ITSELF, reproduced against a synthetic speaker-ordered column: walking
# in table order while carrying a monotonic `lo` floor loses every speaker that sorts
# below one already found. sample's Mac: 2 added, 11 failed.
BIG = []
for _s in sorted(s["speaker"] for s in voice.STARTER_VOICES):
    BIG += [_s] * 10


def probe_big(i):
    return BIG[i] if 0 <= i < len(BIG) else None


def _sweep(specs):
    """The endpoint's floor-carrying walk, in miniature."""
    found, lo = [], 0
    for sp in specs:
        try:
            off = voice.vctk_speaker_bounds(sp["speaker"], probe_big, len(BIG), lo)
        except voice.VctkProbeUnavailable:
            off = None
        if off is not None:
            found.append(sp["speaker"])
            lo = max(lo, off)
    return found


_naive = _sweep(voice.STARTER_VOICES)
check("REGRESSION PIN: the OLD walk (table order + monotonic floor) finds only "
      f"{len(_naive)} of 13 even though every speaker is present — this is the shipped "
      "bug, reproduced", len(_naive) < 13)
check("the FIXED walk (speaker order + monotonic floor) finds all thirteen",
      _sweep(ORDER) == sorted(s["speaker"] for s in voice.STARTER_VOICES))

# ── alternates ───────────────────────────────────────────────────────────────
print("\nstarter_candidates (accent-slot alternates)")
check("the primary speaker is always first",
      voice.starter_candidates(voice.STARTER_VOICES[0])[0] == "p311")
check("the research's named alternates follow it",
      voice.starter_candidates({"speaker": "p345", "alt": ("p360",)}) == ["p345", "p360"])
check("a bare string alt is accepted",
      voice.starter_candidates({"speaker": "p1", "alt": "p2"}) == ["p1", "p2"])
check("junk in the table degrades to just the primary, never to an exception",
      voice.starter_candidates({"speaker": "p1", "alt": 7}) == ["p1"]
      and voice.starter_candidates({"speaker": "p1", "alt": [None, ""]}) == ["p1"]
      and voice.starter_candidates(None) == []
      and voice.starter_candidates({"alt": ("p2",)}) == ["p2"])
check("an alternate that repeats the primary is not tried twice",
      voice.starter_candidates({"speaker": "p1", "alt": ("p1", "p2")}) == ["p1", "p2"])
check("no alternate collides with another slot's PRIMARY (a substitution must not "
      "silently duplicate a voice already in the set)",
      not ({a for s in voice.STARTER_VOICES for a in voice.starter_candidates(s)[1:]}
           & {s["speaker"] for s in voice.STARTER_VOICES}))

# ── the row total ────────────────────────────────────────────────────────────
print("\nvctk_total_rows")
check("the live row count is read off the page rather than assumed",
      voice.vctk_total_rows({"num_rows_total": 88156}) == 88156)
check("a page that grew is believed", voice.vctk_total_rows({"num_rows_total": 99}) == 99)
check("a missing / zero / junk count falls back to the pinned one",
      voice.vctk_total_rows({}) == voice.VCTK_ROWS_TOTAL
      and voice.vctk_total_rows({"num_rows_total": 0}) == voice.VCTK_ROWS_TOTAL
      and voice.vctk_total_rows({"num_rows_total": "many"}) == voice.VCTK_ROWS_TOTAL
      and voice.vctk_total_rows(None) == voice.VCTK_ROWS_TOTAL
      and voice.vctk_total_rows([1, 2]) == voice.VCTK_ROWS_TOTAL)

# ── retry backoff ────────────────────────────────────────────────────────────
print("\nvctk_retry_delay")
check("the backoff is exponential", voice.vctk_retry_delay(0) < voice.vctk_retry_delay(1)
      < voice.vctk_retry_delay(2))
check("it is capped, so a run cannot stall for minutes on one bad offset",
      voice.vctk_retry_delay(20) <= 6.0)
check("jitter is INJECTED, not rolled inside — otherwise this table could not be "
      "asserted at all",
      voice.vctk_retry_delay(0, jitter=0.0) == 0.8
      and abs(voice.vctk_retry_delay(0, jitter=0.5) - 1.2) < 1e-9)
check("a negative attempt degrades to the base delay, never to zero or a crash",
      voice.vctk_retry_delay(-3) == 0.8)

# ── vctk_pick_utterances ─────────────────────────────────────────────────────
print("\nvctk_pick_utterances")


def row(spk, mic, text, src="https://x/a.flac", n="001"):
    return {"row": {"speaker_id": spk, "text": text,
                    "file": f"/x/wav48_silence_trimmed/{spk}/{spk}_{n}_{mic}.flac",
                    "audio": [{"src": src, "type": "audio/flac"}]}}


PAGE = [row("p225", "mic1", "Please call Stella.", "s1", "001"),
        row("p225", "mic2", "Please call Stella.", "s2", "001"),
        row("p225", "mic1", "Ask her to bring these things.", "s3", "002"),
        row("p225", "mic2", "Ask her to bring these things.", "s4", "002"),
        row("p225", "mic1", "Six spoons of fresh snow peas.", "s5", "003"),
        row("p225", "mic2", "Six spoons of fresh snow peas.", "s6", "003"),
        row("p226", "mic1", "Different speaker.", "s7", "001")]
picked = voice.vctk_pick_utterances(PAGE, "p225")
check("three utterances are picked (≈10s once concatenated)", len(picked) == 3)
check("mic1 ONLY — the DPA 4035 omni channel, the universal TTS-recipe convention",
      [p["src"] for p in picked] == ["s1", "s3", "s5"])
check("another speaker's rows are never mixed in",
      all("Different" not in p["text"] for p in picked))
check("the ground-truth transcript rides along with each pick",
      picked[0]["text"] == "Please call Stella.")
check("`want` is honoured", len(voice.vctk_pick_utterances(PAGE, "p225", 1)) == 1)
check("a want of 0 or below still yields at least one rather than nothing",
      len(voice.vctk_pick_utterances(PAGE, "p225", 0)) == 1)
check("a page with none of this speaker's rows yields nothing (a per-slot failure)",
      voice.vctk_pick_utterances(PAGE, "p999") == [])
check("a row with no audio src is skipped rather than saved as a broken clip",
      voice.vctk_pick_utterances(
          [{"row": {"speaker_id": "p1", "text": "t",
                    "file": "/a/p1_001_mic1.flac", "audio": []}}], "p1") == [])
check("a row with no TEXT is skipped — a starter clip with no transcript is the one "
      "thing this whole set exists to avoid",
      voice.vctk_pick_utterances(
          [{"row": {"speaker_id": "p1", "text": "  ",
                    "file": "/a/p1_001_mic1.flac",
                    "audio": [{"src": "s"}]}}], "p1") == [])
check("every surprise JSON shape is total (a mirror change must degrade to 'this "
      "slot failed', never to a 500)",
      all(voice.vctk_pick_utterances(v, "p1") == []
          for v in (None, "x", 7, [], [None], [{"row": "notadict"}],
                    [{"row": {"speaker_id": 1, "audio": "x"}}],
                    [{"row": {"speaker_id": "p1", "file": "/a_mic1.flac",
                              "audio": [5], "text": "t"}}])))

# ── ffmpeg_concat_argv ───────────────────────────────────────────────────────
print("\nffmpeg_concat_argv")
argv = voice.ffmpeg_concat_argv("/ff", ["/a.flac", "/b.flac", "/c.flac"], "/out.wav")
check("every input is passed with its own -i", argv.count("-i") == 3)
check("the concat FILTER is used (no side-car list file to write or clean up)",
      argv[argv.index("-filter_complex") + 1] == "concat=n=3:v=0:a=1")
check("the output is mono", argv[argv.index("-ac") + 1] == "1")
check("…at the starter sample rate",
      argv[argv.index("-ar") + 1] == str(voice.STARTER_SAMPLE_RATE))
check("…and a real wav", argv[argv.index("-f") + 1] == "wav" and argv[-1] == "/out.wav")
check("-nostdin -y, like every other ffmpeg call here (a prompt would hang a request)",
      "-nostdin" in argv and "-y" in argv)
check("n follows the input count", voice.ffmpeg_concat_argv("/ff", ["/a"], "/o")[
      voice.ffmpeg_concat_argv("/ff", ["/a"], "/o").index("-filter_complex") + 1]
      == "concat=n=1:v=0:a=1")
check("every element is a string", all(isinstance(a, str) for a in argv))

# ── on-disk behaviour: listing, containment, transcripts ─────────────────────
print("\nlisting, containment and transcripts")
with tempfile.TemporaryDirectory() as root:
    lib = voice.voices_dir(root)
    st = voice.starter_dir(root)
    os.makedirs(st, exist_ok=True)
    open(os.path.join(lib, "sample.wav"), "w").write("user clip")
    open(os.path.join(st, "us-m-1-p311.wav"), "w").write("starter clip")
    open(os.path.join(st, "notes.txt"), "w").write("not audio")
    voice.write_starter_manifest(
        {"us-m-1-p311.wav": {"text": "Please call Stella. Ask her to bring these "
                                     "things with her from the store.",
                             "slot": "us-m-1", "speaker": "p311",
                             "accent": "American"}}, root)

    ents = voice.library_entries(root)
    names = [e["name"] for e in ents]
    check("the user's own clip is still listed exactly as before",
          "sample.wav" in names)
    check("the starter clip is listed too — it is an ordinary picker chip",
          "us-m-1-p311.wav" in names)
    check("a non-audio file in the starter dir is ignored", "notes.txt" not in names)
    check("the manifest itself never appears as a clip", "starter.json" not in names)
    stent = [e for e in ents if e["name"] == "us-m-1-p311.wav"][0]
    usent = [e for e in ents if e["name"] == "sample.wav"][0]
    check("a starter clip is FLAGGED as one (the panel drops its ✕ delete)",
          stent.get("starter") is True)
    check("a user clip is not flagged", not usent.get("starter"))
    check("the starter entry carries its GROUND-TRUTH transcript, so pinning it "
          "costs no transcription at all",
          stent["ref_text"].startswith("Please call Stella."))
    check("…and its speaker/accent, for the chip tooltip",
          stent["speaker"] == "p311" and stent["accent"] == "American")
    check("the entry carries an absolute path (it is pinned BY PATH, since the "
          "by-name route is basename-flat)", os.path.isabs(stent["path"]))
    check("the manifest round-trips",
          voice.read_starter_manifest(root)["us-m-1-p311.wav"]["speaker"] == "p311")
    check("a missing manifest reads as {} rather than raising",
          voice.read_starter_manifest("/nope/nothing/here") == {})

    # CONTAINMENT — the delete boundary is deliberately unchanged.
    p, why = voice.library_target("us-m-1-p311.wav", root)
    check("a starter clip is NOT reachable through library_target — the delete "
          "endpoint's containment is basename-flat and stays that way",
          p is None and why)
    p, why = voice.library_target("sample.wav", root)
    check("a real library clip still IS", p and why is None)
    for evil in ("../../etc/passwd", "starter/us-m-1-p311.wav", "/etc/passwd",
                 "..", "", "  "):
        got, _ = voice.library_target(evil, root)
        check(f"library_target refuses {evil!r}", got is None)

    # ref_text lookup
    real = os.path.join(st, "us-m-1-p311.wav")
    check("starter_ref_text returns the ground truth for a starter clip",
          voice.starter_ref_text(real, root).startswith("Please call Stella."))
    check("a clip OUTSIDE the starter dir cannot borrow a transcript, even with a "
          "matching basename",
          voice.starter_ref_text(os.path.join(lib, "us-m-1-p311.wav"), root) == "")
    check("an unknown starter file has no transcript, and that is not an error",
          voice.starter_ref_text(os.path.join(st, "nope.wav"), root) == "")
    check("junk input is total",
          all(voice.starter_ref_text(v, root) == "" for v in ("", None, 7)))
    check("the transcript is capped at REF_TEXT_MAX like every other ref_text",
          len(stent["ref_text"]) <= voice.REF_TEXT_MAX)
    check("a starter clip passes the reference-clip validator (so it can be pinned)",
          voice.validate_ref_audio(real) is None)

# ── attribution ──────────────────────────────────────────────────────────────
print("\nattribution (CC BY is only satisfied when the credit is VISIBLE)")
A = voice.VCTK_ATTRIBUTION
check("the licence is named", voice.VCTK_LICENSE == "CC BY 4.0")
check("the corpus is named", "VCTK" in A and "Voice Cloning Toolkit" in A)
check("the authors are named",
      all(n in A for n in ("Yamagishi", "Veaux", "MacDonald")))
check("the publisher is named", "University of Edinburgh" in A)
check("the licence URL is given", "creativecommons.org/licenses/by/4.0" in A)
check("the DOI is given", "10.7488/ds/2645" in A)
check("the CHANGES MADE are declared — CC BY requires it for an adaptation",
      "Changes made" in A and "concatenated" in A)
check("the non-endorsement line is present", "do not endorse" in A)
check("the AI-voice notice exists and says the thing that actually matters",
      "impersonate" in voice.VOICE_AI_NOTICE
      and "AI-generated" in voice.VOICE_AI_NOTICE)

# ── the offset index (what makes a RE-RUN cheap) ──────────────────────────────
print("\nstarter offsets index")
with tempfile.TemporaryDirectory() as td:
    check("no index yet reads as an empty one, not an error",
          voice.read_starter_offsets(td) == {})
    voice.write_starter_offsets({"p225": 0, "p311": 61234}, td)
    check("it round-trips", voice.read_starter_offsets(td) == {"p225": 0, "p311": 61234})
    check("it lives beside the clips and is NOT itself listed as a clip (its suffix is "
          "not one the engine reads)",
          os.path.dirname(voice.starter_offsets_path(td)) == voice.starter_dir(td)
          and voice.normalize_ref_suffix(voice.STARTER_OFFSETS) is None)
    with open(voice.starter_offsets_path(td), "w") as f:
        f.write('{"p225": "nope", "p226": -4, "p227": 12}')
    check("a corrupt entry degrades to 'no cache' for that speaker rather than to a "
          "WRONG offset — a wrong offset would fetch another speaker's voice",
          voice.read_starter_offsets(td) == {"p227": 12})
    with open(voice.starter_offsets_path(td), "w") as f:
        f.write("not json at all")
    check("an unreadable index is simply ignored", voice.read_starter_offsets(td) == {})

# ── starter_present (the re-run skip) ─────────────────────────────────────────
print("\nstarter_present")
with tempfile.TemporaryDirectory() as td:
    sd = voice.starter_dir(td)
    os.makedirs(sd, exist_ok=True)
    check("nothing on disk → nothing to skip",
          voice.starter_present("us-m-1", "p311", td) is None)
    with open(os.path.join(sd, "us-m-1-p311.wav"), "wb") as f:
        f.write(b"x")
    check("the wav is found", voice.starter_present("us-m-1", "p311", td)
          == os.path.join(sd, "us-m-1-p311.wav"))
    # ⚠️ THE THIRD DEFECT: the no-ffmpeg degrade writes .flac, and the old skip test
    # only knew about .wav — so a machine without ffmpeg re-downloaded every clip it
    # already had, on every single click.
    with open(os.path.join(sd, "uk-f-1-p225.flac"), "wb") as f:
        f.write(b"x")
    check("the no-ffmpeg .flac degrade is ALSO recognised as already-present",
          voice.starter_present("uk-f-1", "p225", td)
          == os.path.join(sd, "uk-f-1-p225.flac"))
    open(os.path.join(sd, "us-f-1-p294.wav"), "wb").close()
    check("a zero-byte leftover does NOT count as present",
          voice.starter_present("us-f-1", "p294", td) is None)

# ── CLIP LENGTH GUARD ────────────────────────────────────────────────────────
print("\nwav_duration_secs (exact, header-only)")


def wav_bytes(secs, rate=24000, bits=16, ch=1, data_size=None):
    """A minimal but REAL RIFF/WAVE header + `secs` of silence."""
    byte_rate = rate * ch * bits // 8
    n = int(round(secs * byte_rate))
    ds = n if data_size is None else data_size
    return (b"RIFF" + (36 + n).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
            + ch.to_bytes(2, "little") + rate.to_bytes(4, "little")
            + byte_rate.to_bytes(4, "little")
            + (ch * bits // 8).to_bytes(2, "little") + bits.to_bytes(2, "little")
            + b"data" + ds.to_bytes(4, "little") + b"\0" * n)


for want in (1.0, 9.5, 12.0, 30.0):
    b = wav_bytes(want)
    got = voice.wav_duration_secs(b, len(b))
    check(f"a {want}s wav measures {want}s from its header alone",
          got is not None and abs(got - want) < 0.02)
check("a 48 kHz stereo wav is measured by its byte rate, not by an assumed one",
      abs(voice.wav_duration_secs(wav_bytes(5.0, rate=48000, ch=2),
                                 len(wav_bytes(5.0, rate=48000, ch=2))) - 5.0) < 0.02)
_stream = wav_bytes(7.0, data_size=0)          # what a streaming encoder writes
check("a streamed wav whose data chunk claims 0 bytes falls back to the file size "
      "rather than reporting a zero-length clip",
      voice.wav_duration_secs(_stream, len(_stream)) is not None
      and abs(voice.wav_duration_secs(_stream, len(_stream)) - 7.0) < 0.05)
check("an extra chunk before `data` is walked past, not tripped over",
      voice.wav_duration_secs(
          wav_bytes(3.0)[:12] + b"LIST" + (4).to_bytes(4, "little") + b"INFO"
          + wav_bytes(3.0)[12:], 0) is not None)
check("a non-wav / truncated / empty buffer is UNKNOWN (None), never zero — a guard "
      "that cannot measure must not block",
      voice.wav_duration_secs(b"") is None
      and voice.wav_duration_secs(b"ID3\x04" + b"\0" * 200) is None
      and voice.wav_duration_secs(b"RIFF" + b"\0" * 8) is None
      and voice.wav_duration_secs(None) is None
      and voice.wav_duration_secs(wav_bytes(1.0)[:40]) is None)

print("\nestimate_clip_secs")
with tempfile.TemporaryDirectory() as td:
    wp = os.path.join(td, "a.wav")
    with open(wp, "wb") as f:
        f.write(wav_bytes(20.0))
    s, m = voice.estimate_clip_secs(wp)
    check("a wav is measured exactly and says so", m == "wav-header" and abs(s - 20) < 0.1)
    mp = os.path.join(td, "a.mp3")
    with open(mp, "wb") as f:
        f.write(b"\0" * (40000 * 25))
    s, m = voice.estimate_clip_secs(mp)
    # ⚠️ HEURISTIC, tagged in voice.py: only a wav states its own duration for free.
    check("a non-wav falls back to the size heuristic and SAYS it is an estimate",
          m == "size" and abs(s - 25) < 0.5)
    check("sample's actual clip (7.28 MB mp3) estimates as long enough to act on",
          voice.estimate_clip_secs.__doc__ is not None
          and (7.28 * 1024 * 1024) / voice.NONWAV_EST_BYTES_PER_SEC
          > voice.REF_CLIP_LONG_SECS)
    check("the heuristic is CONSERVATIVE (assumes a high bitrate ⇒ reads short ⇒ errs "
          "toward accepting a real clip, never toward refusing one)",
          voice.NONWAV_EST_BYTES_PER_SEC >= 40000)
    check("a missing / empty file is UNKNOWN, not zero",
          voice.estimate_clip_secs(os.path.join(td, "nope.wav")) == (None, "unknown")
          and voice.estimate_clip_secs("") == (None, "unknown"))

print("\nclip_length_verdict")
check("a normal ~10s reference clip is left completely alone",
      voice.clip_length_verdict(10.0, True) == ("ok", "")
      and voice.clip_length_verdict(10.0, False) == ("ok", ""))
check("the leave-alone band reaches REF_CLIP_LONG_SECS",
      voice.clip_length_verdict(voice.REF_CLIP_LONG_SECS, True)[0] == "ok")
check("a long clip WITH ffmpeg is trimmed", voice.clip_length_verdict(45.0, True)[0] == "trim")
check("the trim message names the bound AND why it is harmless",
      "12s" in voice.clip_length_verdict(45.0, True)[1]
      and "~10s" in voice.clip_length_verdict(45.0, True)[1])
check("an over-long clip with NO ffmpeg is REFUSED",
      voice.clip_length_verdict(45.0, False)[0] == "refuse")
check("the refusal names the limit, the reason, and the way out",
      "30s" in voice.clip_length_verdict(45.0, False)[1]
      and "~10s" in voice.clip_length_verdict(45.0, False)[1]
      and "ffmpeg" in voice.clip_length_verdict(45.0, False)[1])
check("between the two bands with no ffmpeg it is accepted with a warning, not refused",
      voice.clip_length_verdict(20.0, False)[0] == "warn"
      and voice.clip_length_verdict(20.0, False)[1])
check("an UNKNOWN duration is always 'ok' — the guard never blocks what it cannot "
      "measure",
      voice.clip_length_verdict(None, False) == ("ok", "")
      and voice.clip_length_verdict("", True) == ("ok", "")
      and voice.clip_length_verdict("junk", False) == ("ok", "")
      and voice.clip_length_verdict(-5, False) == ("ok", ""))
check("a size-based verdict says 'about', so an estimate is never quoted as a fact",
      "about" in voice.clip_length_verdict(45.0, True, "size")[1]
      and "about" not in voice.clip_length_verdict(45.0, True, "wav-header")[1])
check("the bounds are ordered sensibly",
      voice.REF_CLIP_TRIM_SECS <= voice.REF_CLIP_LONG_SECS < voice.REF_CLIP_MAX_SECS)
check("the trim bound is comfortably ABOVE the ~10s the engine actually reads",
      voice.REF_CLIP_TRIM_SECS >= 10)

print("\ntrim paths + argv")
check("the trimmed copy is a wav in data/voices/trimmed/",
      voice.trimmed_clip_path("/x/y/long.mp3", "/r")
      .startswith(os.path.join(voice.trimmed_dir("/r"), "long-"))
      and voice.trimmed_clip_path("/x/y/long.mp3", "/r").endswith("-12s.wav"))
check("only the BASENAME of the source survives — nothing can climb out of the dir",
      "/" not in os.path.basename(voice.trimmed_clip_path("../../etc/passwd.wav", "/r"))
      and voice.trimmed_clip_path("../../x.wav", "/r").startswith(
          voice.trimmed_dir("/r") + os.sep))
check("trimmed/ is INSIDE the library so the picker can show a pinned copy",
      voice.trimmed_dir("/r").startswith(voice.voices_dir("/r") + os.sep))
check("a trimmed clip is NOT reachable through library_target (the delete boundary is "
      "unchanged — a derived file with a delete button would only strand its own pin)",
      voice.library_target("trimmed/long-12s.wav", "/r")[0] is None)
_TA = voice.ffmpeg_trim_argv("/ff", "/in.mp3", "/out.wav", 12)
check("the trim argv bounds the OUTPUT duration with -t",
      "-t" in _TA and _TA[_TA.index("-t") + 1] == "12"
      and _TA.index("-t") > _TA.index("-i"))
check("it lands mono at the starter sample rate, in wav",
      _TA[-1] == "/out.wav" and "-ac" in _TA and _TA[_TA.index("-ac") + 1] == "1"
      and _TA[_TA.index("-ar") + 1] == str(voice.STARTER_SAMPLE_RATE))
check("it never prompts (-nostdin) and never asks to overwrite (-y)",
      "-nostdin" in _TA and "-y" in _TA)

print("\nthe trimmed subdir shows up in the picker")
with tempfile.TemporaryDirectory() as td:
    os.makedirs(voice.trimmed_dir(td), exist_ok=True)
    with open(os.path.join(voice.trimmed_dir(td), "long-12s.wav"), "wb") as f:
        f.write(wav_bytes(12.0))
    names = {c["name"]: c for c in voice.library_entries(td)}
    check("a trimmed copy is LISTED — otherwise a pin pointing at it would read as "
          "'nothing pinned'", "long-12s.wav" in names)
    check("...and is tagged as trimmed, not as an ordinary recording",
          names.get("long-12s.wav", {}).get("trimmed") is True)

# ── wiring ───────────────────────────────────────────────────────────────────
print("\nwiring")
ASRC = _APP_SOURCE
PSRC = (ROOT / "bridge" / "panel" / "index.html").read_text()
check("the endpoint exists", '@app.post("/api/voice/library/starter")' in ASRC)
check("it fetches from the datasets-server mirror the research verified",
      "datasets-server.huggingface.co/rows" in (ROOT / "bridge" / "voice.py").read_text()
      and "sanchit-gandhi/vctk" in (ROOT / "bridge" / "voice.py").read_text())
check("the fetch URL is /rows — `/filter` is never CALLED (it returned an empty body "
      "for this dataset in repeated testing, so it is documented-and-avoided)",
      voice.VCTK_ROWS_URL.endswith("/rows") and "filter" not in voice.VCTK_ROWS_URL
      and '"where"' not in ASRC)
check("PARTIAL SUCCESS is the design — failures are reported per slot with a reason",
      '"failed": failed' in ASRC and '"reason"' in ASRC)
check("a slot already on disk is SKIPPED, so re-running only fetches what is missing",
      "_voice.starter_present(slot, spk, ROOT)" in ASRC
      and "skipped.append(" in ASRC)
check("THE FIX: the endpoint walks starter_fetch_order(), not the raw table — the `lo` "
      "floor it carries is only sound in ascending speaker order",
      "_voice.starter_fetch_order(_voice.STARTER_VOICES)" in ASRC
      and "for spec in _voice.STARTER_VOICES:" not in ASRC)
check("the floor advances only on a PRIMARY hit (an alternate can sit near the start of "
      "the dataset and would poison the next search)",
      'if used == spec["speaker"]:' in ASRC and "lo = max(lo, offset)" in ASRC)
check("a probe failure is reported as UNREACHABLE, never as 'speaker not found'",
      "except _voice.VctkProbeUnavailable" in ASRC
      and "could not reach the dataset mirror" in ASRC)
check("failures are NEVER cached as answers (the poisoned-offset half of the bug)",
      "raise _voice.VctkProbeUnavailable" in ASRC
      and "probes[off] = sid" in ASRC
      and ASRC.index("raise _voice.VctkProbeUnavailable(err")
      < ASRC.index("probes[off] = sid"))
check("the fetch retries with backoff + jitter rather than losing a voice to one 429",
      "_voice.vctk_retry_delay(" in ASRC and "429" in ASRC
      and "_VCTK_TRIES" in ASRC)
check("a 4xx that is not 429 fails fast — waiting will not turn a 404 into a 200",
      "400 <= r.status_code < 500" in ASRC)
check("requests are PACED, so one click is not 200 requests fired flat out",
      "_VCTK_PACE_SECS" in ASRC)
check("the row total is read off the live page, not assumed",
      "_voice.vctk_total_rows(j)" in ASRC and "total_rows" in ASRC)
check("the offset index is PERSISTED, so a second click spends its requests on the "
      "missing clips instead of re-deriving offsets it already knew",
      "_voice.read_starter_offsets(ROOT)" in ASRC
      and "_voice.write_starter_offsets(known, ROOT)" in ASRC)
check("the run has a wall-clock budget and says so rather than hanging the request",
      "_voice.STARTER_BUDGET_SECS" in ASRC and "ran out of time" in ASRC)
check("a substitution is REPORTED, never silent (it changes the voice and keeps only "
      "the accent slot)",
      '"substituted": substituted' in ASRC and "_voice.starter_candidates(spec)" in ASRC)
check("every failure reason is also printed to the bridge log, so the next diagnosis "
      "does not depend on the panel having been open",
      "starter {f['slot']}" in ASRC)
check("the manifest is written after every slot, so an interrupted run keeps what "
      "it already got", "_voice.write_starter_manifest(man, ROOT)" in ASRC)
check("the temporary per-utterance downloads are always cleaned up",
      "finally:" in ASRC and "os.remove(p)" in ASRC)
check("the attribution travels with the library listing, so the panel can render it "
      "without a second round-trip", '"starter_attribution"' in ASRC)
check("pinning a starter clip uses its stored transcript INSTEAD of calling STT",
      "_voice.starter_ref_text(path, ROOT)" in ASRC
      and ASRC.index("_voice.starter_ref_text(path, ROOT)")
      < ASRC.index("ref_text = await _transcribe_clip(path, audio)"))
check("the panel has one button for the whole set", "getStarterVoices" in PSRC)
check("the panel renders the attribution, not just the endpoint",
      "starter_attribution" in PSRC and "University of Edinburgh" in PSRC)
check("a starter chip pins by ABSOLUTE PATH and passes the transcript",
      "setEntryRef(a.id, c.path, c.ref_text || '')" in PSRC)
check("a starter chip has NO ✕ delete (offering one the bridge would refuse is worse "
      "than offering none)",
      "if (c.starter){" in PSRC
      and PSRC.index("if (c.starter){") < PSRC.index("Remove ' + c.name"))
check("the no-ffmpeg degrade is surfaced honestly rather than silently",
      "no ffmpeg" in PSRC)
check("the panel prints the REASON for every failed slot into the activity feed — "
      "'2 added, 11 failed' with no reason is what made this bug undiagnosable",
      "') failed — ' + f.reason" in PSRC)
check("the panel names the substituted speaker and the slot it filled",
      "for the same accent slot" in PSRC)
check("the status line carries the first reason, not just a count",
      "failed[0] && failed[0].reason" in PSRC)

# ── wiring: the length guard ─────────────────────────────────────────────────
print("\nwiring — the clip length guard")
check("the pin path measures the clip and acts on the verdict",
      "_voice.estimate_clip_secs(path)" in ASRC
      and "_voice.clip_length_verdict(secs, bool(ff), method)" in ASRC)
check("a refusal is a 400 with the reason, not a silent slow render",
      '"refuse"' in ASRC and "status_code=400" in ASRC)
check("a trim pins the BOUNDED COPY, and the original file is only ever read",
      "asyncio.to_thread(_trim_ref_clip, ff, path)" in ASRC
      and "os.remove(src)" not in ASRC.split("def _trim_ref_clip")[1].split("@app.post")[0])
check("a trim drops any ref_text supplied for the ORIGINAL — it no longer describes "
      "the clip being pinned",
      'ref_text = ""' in ASRC.split("asyncio.to_thread(_trim_ref_clip, ff, path)")[1][:600])
check("a failed trim degrades to pinning the clip as it is, rather than to a dead end",
      "the trim failed" in ASRC)
check("the save path applies the same guard and cleans up a refused file rather than "
      "leaving it in the library",
      "note = \"\"" in ASRC and "_voice.clip_length_verdict(secs, bool(_voice.ffmpeg_bin(ROOT))" in ASRC)
check("the pin endpoint hands its note back so the panel can say what it did",
      '"note": length_note' in ASRC)
check("the panel surfaces that note instead of silently pinning a different file",
      "j.note" in PSRC and "feed('voice', j.note)" in PSRC)
check("the picker's note states the trim honestly",
      "trimmed to ~12s" in PSRC and "first ~10" in PSRC)

print("")
print(("FAIL" if FAILS else "OK") + f" — {len(FAILS)} failure(s)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
