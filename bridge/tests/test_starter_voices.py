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
    speaker-ordered column, including "not present" and "probe failed".
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
check("a probe that fails aborts the search rather than guessing",
      voice.vctk_speaker_bounds("p300", lambda i: None, len(COL)) is None)
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
    open(os.path.join(lib, "debi.wav"), "w").write("user clip")
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
          "debi.wav" in names)
    check("the starter clip is listed too — it is an ordinary picker chip",
          "us-m-1-p311.wav" in names)
    check("a non-audio file in the starter dir is ignored", "notes.txt" not in names)
    check("the manifest itself never appears as a clip", "starter.json" not in names)
    stent = [e for e in ents if e["name"] == "us-m-1-p311.wav"][0]
    usent = [e for e in ents if e["name"] == "debi.wav"][0]
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
    p, why = voice.library_target("debi.wav", root)
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

# ── wiring ───────────────────────────────────────────────────────────────────
print("\nwiring")
ASRC = (ROOT / "bridge" / "app.py").read_text()
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
      "skipped.append(name)" in ASRC)
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

print("")
print(("FAIL" if FAILS else "OK") + f" — {len(FAILS)} failure(s)")
for f in FAILS:
    print("  - " + f)
sys.exit(1 if FAILS else 0)
