> **DONE — implemented and shipped (marked 2026-08-20).**

# Update runbook — 2026-08-14 (Fable-QA'd, run each pass on a separate sitting)

Repo edits are already done (pins bumped in the repo's harness.yaml, contract tests
adjusted, Odysseus branch-comment corrected — contract suite now 64, all green).
These are the Mac-side steps. **Do PASS 1 first, verify, then PASS 2 another day,
then PASS 3.** One pass at a time means a regression has exactly one candidate cause.

```bash
REPO=~/"Claude Proj Rootz/New Harness/harness"
DST=~/"Library/Application Support/Harness"
```

## PASS 1 — MLX pair (mlx-vlm 0.6.13 + mlx-audio 0.4.8)

```bash
cd "$DST" && sed -i '' 's/^  mlx_vlm_pin: .*/  mlx_vlm_pin: "0.6.13"/;s/^  mlx_audio_pin: .*/  mlx_audio_pin: "0.4.8"/' harness.yaml
grep -E 'mlx_vlm_pin|mlx_audio_pin' harness.yaml     # MUST show 0.6.13 / 0.4.8
./scripts/install_mlx.sh                             # SNAPSHOT venv — the one the app uses
cd "$REPO" && ./scripts/install_mlx.sh               # keep the repo venv in step
./scripts/ship.sh
```

Verify: an MLX chat model streams · a vision model answers about an image ·
**▶ speak on OmniVoice with your pinned clip = same voice** · `auto` transcribes on
both Parakeet and whisper-base. NOTE: the replay cache still serves old renders —
A/B with FRESH text. Rollback: revert the two pins in BOTH harness.yamls, re-run
install_mlx.sh in both places.

## PASS 2 — Hermes v2026.7.30 → v2026.8.13

```bash
cd "$REPO"
rm -f .git/modules/vendor/hermes/index.lock .git/modules/vendor/hermes/objects/maintenance.lock
git -C vendor/hermes reset --hard
git -C vendor/hermes fetch --tags origin
git -C vendor/hermes checkout v2026.8.13
python3 -m pytest bridge/contract_tests/ -q          # MUST be green before continuing
./scripts/install_component.sh hermes --yes          # repo venv + rebuilds web_dist

rsync -a --delete --exclude='.git' --exclude='node_modules' --exclude='__pycache__' --exclude='*.pyc' \
  "$REPO/vendor/hermes/" "$DST/vendor/hermes/"
"$DST/data/hermes-venv/bin/python" -m pip install -e "$DST/vendor/hermes[all]"   # online
sed -i '' 's/^    pin: v2026\.7\.30.*/    pin: v2026.8.13/' "$DST/harness.yaml"
./scripts/ship.sh
```

**‼️ RESTART HERMES FIRST — `ship.sh` restarts the app and bridge but deliberately
leaves components running, so the OLD Hermes process keeps serving until you stop it.**
ONE command, and it must run **from the SNAPSHOT** (the app's Hermes venv is the one
that got the 0.20.1 install; running it from the repo would start the repo's copy):

```
cd ~/Library/Application\ Support/Harness && ./scripts/start_component.sh hermes
```

That script is a full restart by construction: `hermes dashboard --stop` → `pkill` →
listener-scoped port kill → **re-seeds guards/harness-path-guard into ~/.hermes** →
re-patches the runner endpoint into config.yaml → relaunches. Then confirm the Hermes
tab's sidebar footer reads **v0.20.1** (it says v0.19.1 while the old process is alive).
Then check Hermes tab → Config → Security → `approvals.mode` is still **manual** (the
default is `smart`, which hands approvals to a guardian model and shows no card).

Verify: dashboard :9119 · a Hermes-lane chat streams in the panel · a dangerous
command shows the approval card and Once works · a write outside the workspace
shows the path-guard card · `./scripts/test_hermes.sh` = PASS.
Rollback: `git -C vendor/hermes checkout v2026.7.30` + revert pins + reinstall +
re-rsync + re-pip-install.

## PASS 3 — llama.cpp b10295 → b10427

```bash
cd "$DST" && cp -R data/llamacpp data/llamacpp.b10295.bak     # THIS IS THE ROLLBACK
sed -i '' 's/^  llamacpp_pin: .*/  llamacpp_pin: b10427/' harness.yaml
./scripts/install_llamacpp.sh
cd "$REPO" && cp -R data/llamacpp data/llamacpp.b10295.bak && ./scripts/install_llamacpp.sh
./scripts/ship.sh
```

Verify: runner starts, gguf chat streams, tok/s comparable, no repetition loops ·
a gguf TTS ▶ speak still renders (if one is installed). Rollback:
`rm -rf data/llamacpp && mv data/llamacpp.b10295.bak data/llamacpp` (both places) +
revert the pin.

## What changed / what did NOT

Changed: mlx-vlm 0.6.10→0.6.13 (additive args), mlx-audio 0.4.7→0.4.8 (resampling
quality; the voice-critical files are byte-identical so worker parity is safe),
Hermes →v2026.8.13, llama.cpp →b10427. NOT changed: Odysseus (deferred; its pin is
on the DEV branch — comment corrected, never bump to "latest main"), VoiceStudio,
Voicebox, mlx-lm, mlx-whisper, bun, uv, imageio-ffmpeg.
