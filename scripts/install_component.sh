#!/usr/bin/env bash
# Install a component natively:
#   ./scripts/install_component.sh hermes|odysseus|voicestudio|voicebox|comfyui|unsloth [--yes]
# Shows the plan first; --yes skips the prompt (used by the panel after UI approval).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
NAME="${1:-}"; YES="${2:-}"
case "$NAME" in
  hermes|odysseus|voicestudio|voicebox|comfyui|unsloth) ;;
  *) echo "usage: $0 hermes|odysseus|voicestudio|voicebox|comfyui|unsloth [--yes]"; exit 1 ;;
esac
# hermes/odysseus are pinned SUBMODULES created by bootstrap.sh. voicestudio, voicebox,
# comfyui and unsloth are OPTIONAL components and — like searxng — are plain shallow
# clones this script makes itself, so a default bootstrap never drags in a multi-GB
# optional dep. The skip list is NAME-SCOPED, never a blanket "skip the precheck".
case "$NAME" in voicestudio|voicebox|comfyui|unsloth) _SKIP_GIT_PRECHECK=1 ;; *) _SKIP_GIT_PRECHECK=0 ;; esac
if [[ "$_SKIP_GIT_PRECHECK" != "1" ]]; then
  [[ -e "vendor/$NAME/.git" ]] || {
    echo "vendor/$NAME missing — run bootstrap.sh first:"
    echo "  cd \"$ROOT\" && ./scripts/bootstrap.sh --yes"
    exit 1
  }
fi

plan_hermes="PLAN (hermes):
  - create venv data/hermes-venv (isolated; vendor/ stays pristine)
  - pip install -e vendor/hermes[all]  (~ a few hundred MB of deps)
  - build Hermes's own web dashboard UI (npm --workspace web → hermes_cli/web_dist/, gitignored)
  - config points its model provider at the runner endpoint (patched on Start)
  - serve on port 9119 when started (hermes dashboard: UI + JSON-RPC/WS API)"

plan_odysseus="PLAN (odysseus):
  - create venv data/odysseus-venv
  - pip install -r vendor/odysseus/requirements.txt (+ ddgs for Docker-free web search)
  - run setup.py, seeding admin account (user 'admin', password 'admin123' — CHANGE after first login)
  - connect: register the local Jan endpoint (:1337) as the default chat model
  - serve natively on port 7860 when started"

plan_voicestudio="PLAN (voicestudio) — OPTIONAL, license AGPL-3.0-only:
  - shallow-clone vendor/voicestudio at the pinned tag from harness.yaml (not a submodule)
  - create venv data/voicestudio-venv and install its Python deps
    (torch + transformers + whisperx + pyannote + demucs + sherpa-onnx + mlx ⇒ ~5-8GB;
     needs ~10GB free — speech models (~2.4GB) download later, on first use)
  - provide ffmpeg without Homebrew: reuse yours if you have one, otherwise install the
    imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and copy the
    binary to data/ffmpeg/bin/
  - build the web UI with bun: reuse a bun already on your PATH, otherwise download the
    pinned bun release (~35MB) into data/bun/ — never Homebrew, never sudo, never
    outside this project folder (skipped with a warning if that download fails; the
    backend still boots and serves a stub page)
  - serve on 127.0.0.1:3900 when started (API + UI on one port; no auth, loopback only)"

plan_voicebox="PLAN (voicebox) — OPTIONAL, license MIT:
  - shallow-clone vendor/voicebox at the pinned tag from harness.yaml (not a submodule)
  - create venv data/voicebox-venv (plain python -m venv + pip — this is what the
    project's own justfile does; its dependency graph does NOT resolve any other way)
  - install backend/requirements.txt, then chatterbox-tts and hume-tada with --no-deps,
    then (Apple Silicon) requirements-mlx.txt + mlx-audio --no-deps, then Qwen3-TTS
    from git  (torch + transformers + kokoro + librosa ⇒ several GB, ONLINE ONLY)
  - provide ffmpeg without Homebrew: reuse yours if you have one, otherwise install the
    imageio-ffmpeg wheel (~21MB, bundles a static ffmpeg) into the venv and copy the
    binary to data/ffmpeg/bin/ (the start script puts it on the component's PATH)
  - build the web UI with bun and copy web/dist → frontend/: reuse a bun already on your
    PATH, otherwise download the pinned bun release (~35MB) into data/bun/ — never
    Homebrew, never sudo, never outside this project folder (skipped with a warning if
    that download fails — the backend still serves its JSON API)
  - ⚠️ KNOWN-FRAGILE: five deps need --no-deps / git URLs / a custom package index.
    If resolution breaks, the failure is printed with the log path — it is an upstream
    pin conflict, not a harness bug (upstream last shipped 2026-04-26).
  - ⚠️ NO AUTH: serves 127.0.0.1:17493 with /speak, /transcribe and /mcp wide open"

plan_comfyui="PLAN (comfyui) — OPTIONAL, license GPL-3.0:
  - shallow-clone vendor/comfyui at the pinned tag from harness.yaml (not a submodule)
  - create venv data/comfyui-venv and install its Python deps
    (torch + torchvision + torchaudio + transformers + safetensors + the SPA, which
     ships as a PIP package — no npm/bun build needed; roughly 4-6GB of wheels)
  - on Apple Silicon, upstream's own README says to install a PyTorch NIGHTLY build
    first; that is what this does (falling back to stable PyPI torch if the nightly
    index is unreachable). ⚠ a nightly is a FLOATING build — it is upstream's
    instruction, not a pin we control.
  - create data/comfyui/ as its base directory (models, output, input, user) so it
    never writes into vendor/
  - serve on 127.0.0.1:8188 when started (UI + API on one port, loopback, no auth)
  - ⚠ GPL-3.0: composed at ARM'S LENGTH ONLY — a separate process reached over HTTP,
    never modified, never lifted from (same posture as SearXNG's AGPL)
  - ⚠ its diffusion models load in ITS process, so their RAM is invisible to the
    harness model-RAM ledger (memory.budget_gb) — the same known limit the voice
    components already have
  - image/video models are NOT downloaded here; you add them later, on first use"

plan_unsloth="PLAN (unsloth) — OPTIONAL, license AGPL-3.0-only (Studio) / Apache-2.0 (library):
  - shallow-clone vendor/unsloth at the pinned tag from harness.yaml (not a submodule)
  - create venv data/unsloth-venv and 'pip install -e vendor/unsloth[studio]' — the
    studio extra is upstream's own declared server stack (fastapi/uvicorn/datasets/
    pandas/matplotlib/pymupdf/fastmcp …), a few hundred MB. Training extras (torch et
    al.) are NOT installed here; the tab only needs the Studio server.
  - build its React SPA with bun: reuse a bun already on your PATH, otherwise download
    the pinned bun release (~35MB) into data/bun/ — never Homebrew, never sudo, nothing
    written outside this project folder
  - ⚠ UNLIKE the voice components, a missing SPA build is FATAL: at this pin
    studio/backend/run.py aborts the launch when it cannot resolve frontend/dist for a
    web-UI launch. If the bun build fails, the install still finishes but Start will
    refuse with that reason — re-run this install to retry.
  - we deliberately do NOT run upstream's install.sh (it builds its own install root,
    writes shell shims and downloads a FORKED, floating-tag llama.cpp + its own Node),
    and we never invoke 'unsloth start' (that is its agent-wiring path and it would
    relocate HERMES_HOME — our Hermes is not touched)
  - serve on 127.0.0.1:8899 when started; Studio has its OWN bearer login, which is its
    UI's business — on a loopback launch it auto-fills its bootstrap credential
  - ⚠ AGPL-3.0-only for Studio: composed at ARM'S LENGTH ONLY — separate process over
    HTTP, never modified
  - ⚠ it can download its own llama.cpp and models into its own dirs; contained, but
    those weights are invisible to the harness model-RAM ledger"

var="plan_$NAME"; echo "${!var}"
if [[ "$YES" != "--yes" ]]; then
  read -r -p "Proceed? [y/N] " reply
  [[ "$reply" =~ ^[Yy] ]] || { echo "Aborted — nothing was changed."; exit 1; }
fi

PY=$(command -v python3.12 || command -v python3.11 || command -v python3)

# ── shared helpers for the OPTIONAL shallow-clone components (comfyui / unsloth) ──
# Deliberately small and explicit rather than clever: they encode the three lessons the
# voice pair taught us (pin single-sourced from harness.yaml, the bundled-CPython-first
# interpreter ladder, and `python -m pip` never `bin/pip`).

# _pin_of <component> <key>  — key ∈ repo|pin|port. Block-scoped so a later component's
# key can never be read for an earlier one.
_pin_of() {
  awk "/^  $1:/{f=1; next} f && /^  [a-z]/{exit} f && /^    $2:/{print \$2; exit}" harness.yaml
}

# _clone_pinned <component>  — shallow clone / re-pin, searxng precedent (never a submodule).
_clone_pinned() {
  local n="$1" repo pin
  repo="$(_pin_of "$n" repo)"; pin="$(_pin_of "$n" pin)"
  [[ -n "$repo" && -n "$pin" ]] || { echo "ERROR: components.$n repo/pin missing from harness.yaml"; exit 1; }
  if [[ ! -e "vendor/$n/.git" ]]; then
    echo "[harness] cloning ${n} @ ${pin} (shallow)…"
    git clone --depth 1 --branch "$pin" "$repo" "vendor/$n"
  else
    git -C "vendor/$n" fetch --depth 1 --quiet origin "$pin"
    git -C "vendor/$n" checkout --quiet FETCH_HEAD
  fi
  echo "[harness] vendor/${n} pinned to ${pin}"
}

# _pick_py  — PREFER the harness's own bundled standalone CPython (3.12.x, known-good
# ensurepip) over a possibly-relinked Homebrew python. Exactly the voicebox ladder.
_pick_py() {
  local p
  for p in "$ROOT/data/python-standalone/bin/python3" \
           "$(command -v python3.12 || true)" \
           "$(command -v python3.13 || true)" \
           "$(command -v python3.11 || true)" \
           "$(command -v python3 || true)"; do
    [[ -n "$p" && -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

# _find_uv  — EXPLICIT path list. The bridge spawns this script from a Finder-launched
# app with a MINIMAL PATH, so `command -v uv` alone misses ~/.local/bin/uv (standing rule).
_find_uv() {
  local u
  for u in "$(command -v uv || true)" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv \
           /usr/local/bin/uv "$HOME/.cargo/bin/uv"; do
    [[ -n "$u" && -x "$u" ]] && { echo "$u"; return 0; }
  done
  return 0   # not an error — every caller has a non-uv fallback
}

# _mk_venv <venv-dir> <python> <logfile>  — uv --seed first (it never calls ensurepip),
# then plain venv, then --without-pip + a pip bootstrap. Both real failure modes the
# voicebox install hit are handled here.
_mk_venv() {
  local venv="$1" py="$2" log="$3" uv
  uv="$(_find_uv)"
  if [[ ! -x "$venv/bin/python" ]]; then
    if [[ -n "$uv" ]] && "$uv" venv --python "$py" --seed "$venv" >>"$log" 2>&1; then
      echo "[harness] venv created with uv (--seed)."
    elif "$py" -m venv "$venv" >>"$log" 2>&1; then
      echo "[harness] venv created with $py -m venv."
    elif "$py" -m venv --without-pip "$venv" >>"$log" 2>&1; then
      echo "[harness] venv created without pip (pip bootstrapped below)."
    else
      rm -rf "$venv"
      echo "ERROR: could not create $venv with $py. See $log"
      echo "       Repair options: install uv, or brew reinstall python@3.12."
      exit 1
    fi
  fi
  # A uv-seeded or --without-pip venv can have the pip MODULE without bin/pip — every
  # call below goes through `python -m pip`, and this guarantees the module exists.
  if ! "$venv/bin/python" -m pip --version >/dev/null 2>&1; then
    if "$venv/bin/python" -m ensurepip --upgrade >>"$log" 2>&1; then
      echo "[harness] pip bootstrapped via ensurepip."
    elif [[ -n "$uv" ]] && "$uv" pip install --python "$venv/bin/python" pip >>"$log" 2>&1; then
      echo "[harness] pip bootstrapped via uv."
    else
      echo "ERROR: $venv has no usable pip and it could not be bootstrapped. See $log"
      echo "       Easiest fix: install uv, then re-run the install —"
      echo "         curl -LsSf https://astral.sh/uv/install.sh | sh"
      exit 1
    fi
  fi
}

if [[ "$NAME" == "hermes" ]]; then
  uv venv "data/hermes-venv" --python "$PY" 2>/dev/null || true
  # shellcheck disable=SC1091
  source data/hermes-venv/bin/activate
  uv pip install -e "vendor/hermes[all]" || uv pip install -e "vendor/hermes"
  deactivate
  # Build Hermes's own web dashboard SPA. `hermes dashboard --skip-build` serves the
  # prebuilt output from vendor/hermes/hermes_cli/web_dist/ (both node_modules/ and
  # web_dist/ are gitignored by upstream → this never dirties the submodule / blocks
  # pin-bumps). The `web` workspace has a file: dep on apps/shared (@hermes/shared),
  # so the install must run at the hermes root with --workspace web (not inside web/).
  if command -v npm >/dev/null 2>&1; then
    echo "[harness] building Hermes web dashboard UI (npm --workspace web)…"
    ( cd vendor/hermes \
      && npm install --workspace web --no-audit --no-fund \
      && npm run build --workspace web )
    [[ -f vendor/hermes/hermes_cli/web_dist/index.html ]] \
      && echo "[harness] Hermes web UI built → hermes_cli/web_dist/" \
      || echo "[harness] WARN: Hermes web build finished but web_dist/index.html not found."
  else
    echo "[harness] WARN: npm not found — Hermes dashboard UI not built."
    echo "[harness]   Install Node 18+ then: (cd vendor/hermes && npm install --workspace web && npm run build --workspace web)"
  fi
elif [[ "$NAME" == "voicestudio" ]]; then
  # ── OPTIONAL voice component (AGPL-3.0-only; composed over HTTP, never modified) ──
  # Pin + repo are single-sourced from harness.yaml. Plain shallow clone (searxng
  # precedent) rather than a submodule: optional components must not be cloned by a
  # default bootstrap, and this script must never run `git submodule add`.
  VS_REPO=$(awk '/^  voicestudio:/{f=1; next} f && /^  [a-z]/{exit} f && /^    repo:/{print $2; exit}' harness.yaml)
  VS_PIN=$(awk '/^  voicestudio:/{f=1; next} f && /^  [a-z]/{exit} f && /^    pin:/{print $2; exit}' harness.yaml)
  [[ -n "$VS_REPO" && -n "$VS_PIN" ]] || {
    echo "ERROR: components.voicestudio repo/pin missing from harness.yaml"; exit 1; }
  if [[ ! -e vendor/voicestudio/.git ]]; then
    echo "[harness] cloning voicestudio @ $VS_PIN (shallow)…"
    git clone --depth 1 --branch "$VS_PIN" "$VS_REPO" vendor/voicestudio
  else
    # Same idiom as bootstrap.sh's add_submodule: fetch the pin shallowly, detach onto it.
    git -C vendor/voicestudio fetch --depth 1 --quiet origin "$VS_PIN"
    git -C vendor/voicestudio checkout --quiet FETCH_HEAD
  fi
  echo "[harness] vendor/voicestudio pinned to $VS_PIN"
  [[ -f vendor/voicestudio/backend/main.py ]] || {
    echo "ERROR: vendor/voicestudio/backend/main.py not found at $VS_PIN — upstream layout"
    echo "       changed; scripts/start_component.sh launches backend.main:app."
    exit 1; }

  # 1. Python deps. Prefer uv + the committed uv.lock (reproducible), with
  #    UV_PROJECT_ENVIRONMENT redirecting the env OUT of vendor/ (uv sync would
  #    otherwise create vendor/voicestudio/.venv — we never write into vendor/).
  VS_VENV="$ROOT/data/voicestudio-venv"
  VS_OK=0
  if command -v uv >/dev/null 2>&1 && [[ -f vendor/voicestudio/uv.lock ]]; then
    echo "[harness] installing voicestudio deps with uv (from uv.lock) — this is a big download…"
    if UV_PROJECT_ENVIRONMENT="$VS_VENV" uv sync --frozen --project vendor/voicestudio; then
      VS_OK=1
    else
      echo "[harness] WARN: 'uv sync --frozen' failed — falling back to a plain venv install."
    fi
  fi
  if [[ "$VS_OK" != "1" ]]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv "data/voicestudio-venv" --python "$PY" 2>/dev/null || true
      # shellcheck disable=SC1091
      source data/voicestudio-venv/bin/activate
      uv pip install -U "setuptools>=75,<80" wheel
      if [[ -f vendor/voicestudio/requirements.txt ]]; then
        uv pip install -r vendor/voicestudio/requirements.txt
      else
        uv pip install -e vendor/voicestudio
      fi
      deactivate
    else
      echo "[harness] uv not found — falling back to python venv + pip."
      "$PY" -m venv data/voicestudio-venv
      "$VS_VENV/bin/pip" install -U pip "setuptools>=75,<80" wheel
      if [[ -f vendor/voicestudio/requirements.txt ]]; then
        "$VS_VENV/bin/pip" install -r vendor/voicestudio/requirements.txt
      else
        "$VS_VENV/bin/pip" install -e vendor/voicestudio
      fi
    fi
  fi
  # setuptools floor/cap in THIS venv only: whisperx still imports pkg_resources at
  # RUNTIME, and upstream caps setuptools <80. Best-effort — never fail the install.
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VS_VENV/bin/python" "setuptools>=75,<80" >/dev/null 2>&1 || true
  else
    "$VS_VENV/bin/pip" install "setuptools>=75,<80" >/dev/null 2>&1 || true
  fi
  [[ -x "$VS_VENV/bin/python" ]] || { echo "ERROR: data/voicestudio-venv was not created."; exit 1; }

  # 2a. ffmpeg (whisperx / demucs shell out to it). NO brew: ensure_ffmpeg.sh reuses a
  #     system ffmpeg if the user has one, else lands a static binary from the
  #     imageio-ffmpeg wheel at data/ffmpeg/bin/ffmpeg. Best-effort — `|| true` keeps
  #     `set -e` from aborting the install when there is no network / no wheel.
  VS_FF="$(bash scripts/ensure_ffmpeg.sh "$VS_VENV" || true)"
  [[ -n "$VS_FF" ]] || echo "[harness] WARN: no ffmpeg available — transcription/conversion may fail."

  # 2b. Web UI (Vite SPA, built with bun). The backend mounts frontend/dist at / on the
  #    SAME port; if dist is absent it still boots and serves a stub — so a missing bun
  #    is a WARNING, never an install failure.
  #    NO brew prerequisite: ensure_bun.sh reuses a bun already on PATH, else downloads
  #    the pinned release into data/bun/. `|| true` is REQUIRED here — this script runs
  #    under `set -e` and an un-buildable optional web UI must never fail the install.
  BUN="$(bash scripts/ensure_bun.sh || true)"
  if [[ -n "$BUN" ]]; then
    echo "[harness] building the voicestudio web UI (bun)…"
    VS_WEB=""
    [[ -f vendor/voicestudio/frontend/package.json ]] && VS_WEB="vendor/voicestudio/frontend"
    [[ -z "$VS_WEB" && -f vendor/voicestudio/package.json ]] && VS_WEB="vendor/voicestudio"
    if [[ -n "$VS_WEB" ]]; then
      # BUN_INSTALL / BUN_INSTALL_CACHE_DIR keep bun's global dir + package cache inside
      # data/ instead of ~/.bun — the harness never writes outside the project folder.
      # PATH also carries bun so package.json scripts that call `bun`/`bunx` by name work.
      ( cd "$VS_WEB" \
        && PATH="$(cd "$(dirname "$BUN")" && pwd):$PATH" \
           BUN_INSTALL="$ROOT/data/bun" \
           BUN_INSTALL_CACHE_DIR="$ROOT/data/bun/cache" \
           bash -c 'bun install && bun run build' ) \
        || echo "[harness] WARN: the bun build failed — the tab will show the backend's stub page."
    else
      echo "[harness] WARN: no package.json found — skipping the web UI build."
    fi
    [[ -f vendor/voicestudio/frontend/dist/index.html ]] \
      && echo "[harness] voicestudio web UI built → frontend/dist/" \
      || echo "[harness] WARN: frontend/dist/index.html not found after the build."
  else
    echo "[harness] WARN: bun could not be provisioned — the voicestudio web UI was NOT built."
    echo "[harness]   The component still starts and serves a stub page. The reason is"
    echo "[harness]   printed above (usually no network); re-run this install to retry:"
    echo "[harness]   ./scripts/install_component.sh voicestudio --yes"
  fi
  echo "[harness] NOTE: voicestudio is AGPL-3.0-only and binds 127.0.0.1 with NO authentication —"
  echo "[harness]   never expose :3900 beyond loopback (that includes any future Tailscale hop)."
elif [[ "$NAME" == "voicebox" ]]; then
  # ── OPTIONAL voice component #2 (MIT; composed over HTTP, never modified) ──────
  # Same delivery shape as voicestudio: plain shallow clone (searxng precedent), venv
  # under data/, nothing written into vendor/ except the SPA the backend must serve.
  VB_REPO=$(awk '/^  voicebox:/{f=1; next} f && /^  [a-z]/{exit} f && /^    repo:/{print $2; exit}' harness.yaml)
  VB_PIN=$(awk '/^  voicebox:/{f=1; next} f && /^  [a-z]/{exit} f && /^    pin:/{print $2; exit}' harness.yaml)
  [[ -n "$VB_REPO" && -n "$VB_PIN" ]] || {
    echo "ERROR: components.voicebox repo/pin missing from harness.yaml"; exit 1; }
  if [[ ! -e vendor/voicebox/.git ]]; then
    echo "[harness] cloning voicebox @ $VB_PIN (shallow)…"
    git clone --depth 1 --branch "$VB_PIN" "$VB_REPO" vendor/voicebox
  else
    git -C vendor/voicebox fetch --depth 1 --quiet origin "$VB_PIN"
    git -C vendor/voicebox checkout --quiet FETCH_HEAD
  fi
  echo "[harness] vendor/voicebox pinned to $VB_PIN"
  [[ -f vendor/voicebox/backend/main.py ]] || {
    echo "ERROR: vendor/voicebox/backend/main.py not found at $VB_PIN — upstream layout"
    echo "       changed; scripts/start_component.sh launches 'python -m backend.main'."
    exit 1; }
  [[ -f vendor/voicebox/backend/requirements.txt ]] || {
    echo "ERROR: vendor/voicebox/backend/requirements.txt not found at $VB_PIN."; exit 1; }

  # 1. Interpreter. PREFER the harness's own bundled standalone CPython when present:
  #    it is 3.12.x (exactly upstream's preferred minor), it is the interpreter that
  #    already built every other venv here, and — unlike a Homebrew python that has
  #    been upgraded/relinked — its `ensurepip` is known-good. A broken system
  #    ensurepip is a REAL failure we hit: `python3.12 -m venv` aborts with
  #    "ensurepip --upgrade --default-pip returned non-zero exit status 1".
  VB_PY=""
  for _p in "$ROOT/data/python-standalone/bin/python3" \
            "$(command -v python3.12 || true)" \
            "$(command -v python3.13 || true)" \
            "$(command -v python3 || true)"; do
    [[ -n "$_p" && -x "$_p" ]] && { VB_PY="$_p"; break; }
  done
  [[ -n "$VB_PY" ]] || { echo "ERROR: no python3 found — install Python 3.12 (brew install python@3.12)."; exit 1; }
  echo "[harness] voicebox interpreter: $VB_PY"
  VB_MINOR=$("$VB_PY" -c 'import sys; print(sys.version_info[1])')
  if [[ "$VB_MINOR" -gt 13 ]]; then
    echo "[harness] WARN: $VB_PY is Python 3.$VB_MINOR — voicebox's ML pins may not build."
    echo "[harness]   Recommended: brew install python@3.12, then re-run this install."
  fi
  # ffmpeg is a RUNTIME requirement (transcription / audio conversion). It is provisioned
  # AFTER the venv exists (branch 2b below) because the no-brew path installs the
  # imageio-ffmpeg wheel into that venv. Nothing to do here.

  # 2. Python deps — MIRROR of upstream's `just setup-python` (unix recipe), which is
  #    plain `python -m venv` + pip. We deliberately do NOT shell out to `just`: its
  #    recipe hardcodes the venv at vendor/voicebox/backend/venv, and we never write a
  #    venv into vendor/. We also do NOT use uv here — the recipe depends on pip's
  #    ordering semantics (--no-deps installs layered ON TOP of an already-resolved
  #    set) and on a --find-links line inside requirements.txt.
  #    ⚠️ KNOWN-FRAGILE: chatterbox-tts / hume-tada / mlx-audio must be --no-deps
  #    (mutually incompatible torch+numpy pins); linacodec + Zipvoice + Qwen3-TTS come
  #    from git URLs; piper-phonemize needs the k2-fsa --find-links index. This is why
  #    voicebox is ONLINE-ONLY and is not part of the fat/offline wheelhouse.
  VB_VENV="$ROOT/data/voicebox-venv"
  # (kept for reference only — every call goes through `python -m pip`, see vb_pip)
  VB_PIP="$VB_VENV/bin/python -m pip"
  mkdir -p "$ROOT/data/logs"
  VB_ILOG="$ROOT/data/logs/voicebox-install.log"
  : > "$VB_ILOG"
  # Venv creation. TWO distinct failure modes are handled here, both hit for real:
  #   (a) a broken/relinked Homebrew python → `python -m venv` ABORTS in ensurepip;
  #   (b) a standalone python without a working ensurepip → `python -m venv` SUCCEEDS
  #       but the venv has NO pip, and the next step dies on "bin/pip: not found".
  # uv sidesteps both (it seeds pip itself and never calls ensurepip), so it is tried
  # FIRST — the harness already relies on uv elsewhere (voicestudio installs with it).
  # Resolve uv EXPLICITLY: the app is launched from Finder with a minimal PATH, so
  # `command -v uv` misses a uv in ~/.local/bin (its default install location) even
  # though the same shell finds /opt/homebrew/bin/bun. That miss is why both pip
  # bootstrap routes were unavailable on Debi's machine.
  VB_UV=""
  for _u in "$(command -v uv || true)" "$HOME/.local/bin/uv" /opt/homebrew/bin/uv \
            /usr/local/bin/uv "$HOME/.cargo/bin/uv"; do
    [[ -n "$_u" && -x "$_u" ]] && { VB_UV="$_u"; break; }
  done
  [[ -n "$VB_UV" ]] && echo "[harness] uv: $VB_UV" || echo "[harness] uv: not found"

  if [[ ! -x "$VB_VENV/bin/python" ]]; then
    if [[ -n "$VB_UV" ]] && "$VB_UV" venv --python "$VB_PY" --seed "$VB_VENV" >>"$VB_ILOG" 2>&1; then
      echo "[harness] venv created with uv (--seed)."
    elif "$VB_PY" -m venv "$VB_VENV" >>"$VB_ILOG" 2>&1; then
      echo "[harness] venv created with $VB_PY -m venv."
    elif "$VB_PY" -m venv --without-pip "$VB_VENV" >>"$VB_ILOG" 2>&1; then
      echo "[harness] venv created without pip (pip bootstrapped below)."
    else
      rm -rf "$VB_VENV"
      echo "ERROR: could not create data/voicebox-venv with $VB_PY. See $VB_ILOG"
      echo "       Repair options: install uv, or brew reinstall python@3.12."
      exit 1
    fi
  fi
  # Guarantee pip EXISTS in the venv regardless of how it was made (failure mode (b)).
  if ! "$VB_VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    echo "[harness] venv has no pip — bootstrapping…"
    # 1) ensurepip (absent on uv-style standalone pythons), 2) uv, 3) the FAT app's
    # bundled wheelhouse via the pip-wheel zipapp trick — a pip .whl is directly
    # executable, which is exactly how a python that ships no ensurepip gets seeded.
    # (3) needs no network and no extra tooling, so it is the reliable last resort.
    VB_WHEELS=""
    for _w in "$ROOT/../wheelhouse" /Applications/Harness.app/Contents/Resources/wheelhouse \
              "$HOME/Applications/Harness.app/Contents/Resources/wheelhouse"; do
      [[ -d "$_w" ]] && { VB_WHEELS="$_w"; break; }
    done
    VB_PIPWHL=""
    [[ -n "$VB_WHEELS" ]] && VB_PIPWHL=$(ls "$VB_WHEELS"/pip-*.whl 2>/dev/null | head -1)

    if "$VB_VENV/bin/python" -m ensurepip --upgrade >>"$VB_ILOG" 2>&1; then
      echo "[harness] pip bootstrapped via ensurepip."
    elif [[ -n "$VB_UV" ]] \
         && "$VB_UV" pip install --python "$VB_VENV/bin/python" pip >>"$VB_ILOG" 2>&1; then
      echo "[harness] pip bootstrapped via uv."
    elif [[ -n "$VB_PIPWHL" ]] \
         && "$VB_VENV/bin/python" "$VB_PIPWHL/pip" install --no-index \
              --find-links "$VB_WHEELS" pip setuptools wheel >>"$VB_ILOG" 2>&1; then
      echo "[harness] pip bootstrapped from the bundled wheelhouse ($VB_WHEELS)."
    else
      echo "ERROR: data/voicebox-venv has no usable pip and it could not be bootstrapped."
      echo "       tried: ensurepip, uv (${VB_UV:-not found}), wheelhouse (${VB_WHEELS:-not found})"
      echo "       See $VB_ILOG"
      echo "       Easiest fix: install uv, then re-run the install —"
      echo "         curl -LsSf https://astral.sh/uv/install.sh | sh"
      exit 1
    fi
  fi
  # `python -m pip` rather than the bin/pip script: a uv-seeded or --without-pip venv
  # may have the MODULE without the console script (the exact "bin/pip: No such file
  # or directory" failure we hit).
  vb_pip() {
    echo "[harness] pip $*"
    if ! "$VB_VENV/bin/python" -m pip install "$@" 2>&1 | tee -a "$VB_ILOG"; then
      echo ""
      echo "ERROR: voicebox dependency install FAILED at: pip install $*"
      echo "       full log: $VB_ILOG"
      echo "       voicebox has a KNOWN-FRAGILE dependency graph (five packages with"
      echo "       mutually conflicting pins) and upstream is stale (last push 2026-04-26)."
      echo "       This is an upstream resolution problem, not a harness bug. It needs"
      echo "       network access; there is no offline path. Re-run in a terminal with:"
      echo "         ./scripts/install_component.sh voicebox --yes"
      exit 1
    fi
  }
  vb_pip --upgrade pip
  vb_pip -r "vendor/voicebox/backend/requirements.txt"
  # --no-deps: chatterbox-tts pins numpy<1.26 / torch==2.6; hume-tada pins torch>=2.7,<2.8.
  vb_pip --no-deps chatterbox-tts
  vb_pip --no-deps hume-tada
  if [[ "$(uname -m)" == "arm64" && "$(uname)" == "Darwin" ]]; then
    echo "[harness] Apple Silicon detected — installing the MLX backend…"
    vb_pip -r "vendor/voicebox/backend/requirements-mlx.txt"
    # requirements-mlx.txt deliberately omits mlx-audio (it declares transformers>=5,
    # which fights the transformers<=4.57.6 cap) — upstream installs it --no-deps after.
    vb_pip --no-deps "mlx-audio==0.4.1"
  fi
  # Qwen3-TTS from git (upstream installs this over the PyPI qwen-tts in requirements).
  # ⚠️ floating HEAD — like linacodec/Zipvoice this is not reproducible across installs.
  vb_pip "git+https://github.com/QwenLM/Qwen3-TTS.git"
  [[ -x "$VB_VENV/bin/python" ]] || { echo "ERROR: data/voicebox-venv was not created."; exit 1; }

  # 2b. ffmpeg — NO brew. ensure_ffmpeg.sh reuses a system ffmpeg if the user has one,
  #     otherwise installs the imageio-ffmpeg wheel into THIS venv and copies its
  #     bundled static binary to data/ffmpeg/bin/ffmpeg. start_component.sh prepends
  #     that dir to PATH so the running backend finds it. Best-effort: `|| true` so a
  #     failure here can never abort the (already very expensive) install.
  VB_FF="$(bash scripts/ensure_ffmpeg.sh "$VB_VENV" || true)"
  if [[ -n "$VB_FF" ]]; then
    echo "[harness] voicebox ffmpeg → $VB_FF"
  else
    echo "[harness] WARN: no ffmpeg available — transcription/conversion will fail."
    echo "[harness]   (reason printed above; re-run the install to retry)"
  fi

  # 3. Web UI. The backend serves an SPA ONLY from <repo-root>/frontend, and no
  #    non-Docker path creates it: build web/ with bun, then copy web/dist → frontend/.
  #    Missing bun is a WARNING — the JSON API and /mcp still work without a UI.
  #    NO brew prerequisite: ensure_bun.sh reuses a bun on PATH or downloads the pinned
  #    release into data/bun/. `|| true` is REQUIRED (this script runs under `set -e`).
  BUN="$(bash scripts/ensure_bun.sh || true)"
  if [[ -n "$BUN" ]]; then
    echo "[harness] building the voicebox web UI (bun)…"
    # BUN_INSTALL / BUN_INSTALL_CACHE_DIR keep bun's global dir + package cache inside
    # data/ instead of ~/.bun — the harness never writes outside the project folder.
    ( cd vendor/voicebox \
      && PATH="$(cd "$(dirname "$BUN")" && pwd):$PATH" \
         BUN_INSTALL="$ROOT/data/bun" \
         BUN_INSTALL_CACHE_DIR="$ROOT/data/bun/cache" \
         bash -c 'bun install && bun run build:web' ) \
      || echo "[harness] WARN: the bun build failed — the tab will have no UI (API only)."
    if [[ -f vendor/voicebox/web/dist/index.html ]] \
       && ! git -C vendor/voicebox ls-files --error-unmatch frontend >/dev/null 2>&1; then
      # (the ls-files guard: if upstream ever TRACKS frontend/, never clobber it)
      rm -rf vendor/voicebox/frontend
      cp -R vendor/voicebox/web/dist vendor/voicebox/frontend
      # frontend/ is NOT in upstream's .gitignore (only Docker ever creates it), so
      # ignore it LOCALLY to keep the vendored checkout clean for the next pin-bump.
      # .git/info/exclude is git metadata, not upstream content — vendor/ stays pristine.
      if [[ -d vendor/voicebox/.git/info ]]; then
        grep -qx 'frontend/' vendor/voicebox/.git/info/exclude 2>/dev/null \
          || echo 'frontend/' >> vendor/voicebox/.git/info/exclude
      fi
      echo "[harness] voicebox web UI built → vendor/voicebox/frontend/"
    else
      echo "[harness] WARN: web/dist/index.html not found after the build — API only."
    fi
  else
    echo "[harness] WARN: bun could not be provisioned — the voicebox web UI was NOT built."
    echo "[harness]   The component still starts and serves its JSON API + /mcp. The reason"
    echo "[harness]   is printed above (usually no network); re-run this install to retry:"
    echo "[harness]   ./scripts/install_component.sh voicebox --yes"
  fi
  echo "[harness] NOTE: voicebox is MIT, but ships NO AUTHENTICATION — /speak, /transcribe"
  echo "[harness]   and /mcp are open to anything that reaches :17493. Loopback only;"
  echo "[harness]   never expose it (that includes any future Tailscale hop)."
elif [[ "$NAME" == "comfyui" ]]; then
  # ── OPTIONAL image/video generation component (GPL-3.0; composed over HTTP, never
  #    modified, never lifted from — arm's-length only, same posture as SearXNG). ───
  _clone_pinned comfyui
  [[ -f vendor/comfyui/main.py ]] || {
    echo "ERROR: vendor/comfyui/main.py not found at the pin — upstream layout changed;"
    echo "       scripts/start_component.sh launches 'python main.py'."
    exit 1; }
  [[ -f vendor/comfyui/requirements.txt ]] || {
    echo "ERROR: vendor/comfyui/requirements.txt not found at the pin."; exit 1; }

  CU_VENV="$ROOT/data/comfyui-venv"
  mkdir -p "$ROOT/data/logs"
  CU_ILOG="$ROOT/data/logs/comfyui-install.log"
  : > "$CU_ILOG"
  CU_PY="$(_pick_py)" || { echo "ERROR: no python3 found — install Python 3.12."; exit 1; }
  echo "[harness] comfyui interpreter: $CU_PY"
  # upstream pyproject at the pin declares requires-python >= 3.10
  CU_MINOR=$("$CU_PY" -c 'import sys; print(sys.version_info[1])')
  if [[ "$CU_MINOR" -lt 10 ]]; then
    echo "ERROR: $CU_PY is Python 3.$CU_MINOR — ComfyUI needs >= 3.10 at this pin."; exit 1
  fi
  _mk_venv "$CU_VENV" "$CU_PY" "$CU_ILOG"

  cu_pip() {
    echo "[harness] pip $*"
    if ! "$CU_VENV/bin/python" -m pip install "$@" 2>&1 | tee -a "$CU_ILOG"; then
      echo ""
      echo "ERROR: comfyui dependency install FAILED at: pip install $*"
      echo "       full log: $CU_ILOG"
      echo "       This install is ONLINE-ONLY (torch + the SPA package are several GB)."
      echo "       Re-run in a terminal with: ./scripts/install_component.sh comfyui --yes"
      exit 1
    fi
  }
  cu_pip --upgrade pip
  # Apple Silicon: upstream's OWN README (### Apple Mac silicon, at this pin) says
  #   "1. Install pytorch nightly … make sure to install the latest pytorch nightly."
  # so that is what we do, and it is cited rather than invented. ⚠ a nightly is a
  # FLOATING build — not reproducible across time, and not something we pin. If the
  # nightly index is unreachable we fall back to stable PyPI torch (which does have MPS)
  # and say so, rather than failing an otherwise fine install.
  if [[ "$(uname -m)" == "arm64" && "$(uname)" == "Darwin" ]]; then
    echo "[harness] Apple Silicon — installing the PyTorch NIGHTLY build (upstream README's instruction)…"
    if "$CU_VENV/bin/python" -m pip install --pre torch torchvision torchaudio \
         --index-url https://download.pytorch.org/whl/nightly/cpu 2>&1 | tee -a "$CU_ILOG"; then
      echo "[harness] torch nightly installed."
    else
      echo "[harness] WARN: the PyTorch nightly index was unreachable — falling back to"
      echo "[harness]   stable torch from PyPI (MPS works there too; upstream simply"
      echo "[harness]   recommends nightly for the newest Metal fixes)."
    fi
  fi
  cu_pip -r vendor/comfyui/requirements.txt
  [[ -x "$CU_VENV/bin/python" ]] || { echo "ERROR: data/comfyui-venv was not created."; exit 1; }

  # Base directory. ⚠ MANDATORY: ComfyUI's default writes models/ output/ input/ user/
  # NEXT TO main.py, i.e. straight into vendor/. start_component.sh always passes
  # --base-directory; create it here so the first Start has somewhere to write.
  mkdir -p "$ROOT/data/comfyui"
  echo "[harness] comfyui base directory → $ROOT/data/comfyui (models/output/input/user)"
  echo "[harness] NOTE: comfyui is GPL-3.0. The harness composes it at ARM'S LENGTH —"
  echo "[harness]   a separate process reached over HTTP on 127.0.0.1:8188, never edited."
  echo "[harness]   It binds loopback with NO authentication; never expose that port."
  echo "[harness]   Its models load in ITS process, so they are invisible to the harness"
  echo "[harness]   model-RAM ledger (memory.budget_gb) — a known, accepted limit."
elif [[ "$NAME" == "unsloth" ]]; then
  # ── OPTIONAL training/serving studio (AGPL-3.0-only for studio/, Apache-2.0 for the
  #    training library; composed over HTTP, never modified). ─────────────────────────
  _clone_pinned unsloth
  [[ -f vendor/unsloth/studio/backend/run.py ]] || {
    echo "ERROR: vendor/unsloth/studio/backend/run.py not found at the pin — upstream"
    echo "       layout changed; scripts/start_component.sh launches 'unsloth studio'."
    exit 1; }
  [[ -f vendor/unsloth/pyproject.toml ]] || {
    echo "ERROR: vendor/unsloth/pyproject.toml not found at the pin."; exit 1; }

  US_VENV="$ROOT/data/unsloth-venv"
  mkdir -p "$ROOT/data/logs"
  US_ILOG="$ROOT/data/logs/unsloth-install.log"
  : > "$US_ILOG"
  US_PY="$(_pick_py)" || { echo "ERROR: no python3 found — install Python 3.12."; exit 1; }
  echo "[harness] unsloth interpreter: $US_PY"
  # upstream pyproject at the pin declares requires-python >=3.9,<3.15
  US_MINOR=$("$US_PY" -c 'import sys; print(sys.version_info[1])')
  if [[ "$US_MINOR" -lt 9 || "$US_MINOR" -ge 15 ]]; then
    echo "ERROR: $US_PY is Python 3.$US_MINOR — unsloth declares >=3.9,<3.15 at this pin."; exit 1
  fi
  _mk_venv "$US_VENV" "$US_PY" "$US_ILOG"

  us_pip() {
    echo "[harness] pip $*"
    if ! "$US_VENV/bin/python" -m pip install "$@" 2>&1 | tee -a "$US_ILOG"; then
      echo ""
      echo "ERROR: unsloth dependency install FAILED at: pip install $*"
      echo "       full log: $US_ILOG"
      echo "       This install is ONLINE-ONLY. Re-run in a terminal with:"
      echo "         ./scripts/install_component.sh unsloth --yes"
      exit 1
    fi
  }
  us_pip --upgrade pip
  # The [studio] extra is upstream's OWN declared server stack (pyproject.toml
  # [project.optional-dependencies].studio at the pin). We deliberately install ONLY
  # that — the training extras (torch/triton/…) are a separate, much heavier ask and the
  # tab does not need them. Editable so the SPA we build below is found in place.
  us_pip -e "vendor/unsloth[studio]"
  [[ -x "$US_VENV/bin/unsloth" ]] || {
    echo "[harness] WARN: the 'unsloth' console script is not in data/unsloth-venv/bin —"
    echo "[harness]   start_component.sh falls back to 'python -m unsloth_cli'."; }

  # SPA. ⚠ UNLIKE voicestudio/voicebox this is NOT optional: at this pin
  # studio/backend/run.py's _missing_frontend_is_fatal() returns True for any launch that
  # is not --api-only, so a web-UI launch with no frontend/dist ABORTS. We still only
  # WARN here (an install that got the venv right should not be thrown away), and
  # start_component.sh refuses up front with the same reason.
  BUN="$(bash scripts/ensure_bun.sh || true)"
  if [[ -n "$BUN" ]]; then
    echo "[harness] building the unsloth Studio SPA (bun)…"
    ( cd vendor/unsloth/studio/frontend \
      && PATH="$(cd "$(dirname "$BUN")" && pwd):$PATH" \
         BUN_INSTALL="$ROOT/data/bun" \
         BUN_INSTALL_CACHE_DIR="$ROOT/data/bun/cache" \
         bash -c 'bun install && bun run build' ) \
      || echo "[harness] WARN: the bun build failed — see above."
  else
    echo "[harness] WARN: bun could not be provisioned (reason printed above)."
  fi
  if [[ -f vendor/unsloth/studio/frontend/dist/index.html ]]; then
    echo "[harness] unsloth Studio SPA built → studio/frontend/dist/"
  else
    echo "[harness] WARN: studio/frontend/dist/index.html is MISSING."
    echo "[harness]   Unsloth Studio REFUSES to start a web-UI launch without it, so the"
    echo "[harness]   tab will not work until this build succeeds. Re-run the install:"
    echo "[harness]   ./scripts/install_component.sh unsloth --yes"
  fi
  echo "[harness] NOTE: Unsloth Studio is AGPL-3.0-only (the training library is Apache-2.0)."
  echo "[harness]   The harness composes it at ARM'S LENGTH — a separate process on"
  echo "[harness]   127.0.0.1:8899, never edited. It has its OWN login, handled in its own UI."
  echo "[harness]   We never run 'unsloth start' and never set HERMES_HOME: that is its"
  echo "[harness]   agent-wiring path and it must not touch your ~/.hermes."
  echo "[harness]   Models it loads live in ITS process — invisible to memory.budget_gb."
else
  uv venv "data/odysseus-venv" --python "$PY" 2>/dev/null || true
  # shellcheck disable=SC1091
  source data/odysseus-venv/bin/activate
  uv pip install -r vendor/odysseus/requirements.txt
  uv pip install ddgs || true          # Docker-free web search provider
  # Deterministic admin (works both interactively and with --yes): setup.py uses these
  # env creds and skips the prompt / random-password path. 8-char minimum enforced by Odysseus.
  ( cd vendor/odysseus && ODYSSEUS_ADMIN_USER=admin ODYSSEUS_ADMIN_PASSWORD=admin123 python setup.py )
  # Connect step (one-switch): wire Odysseus to the local Jan endpoint as default model.
  ( cd vendor/odysseus && python "$ROOT/scripts/seed_odysseus_jan.py" ) || \
    echo "[harness] note: Jan not reachable yet — endpoint seeded; model auto-discovers on Start"
  deactivate
fi

# flip installed: true in harness.yaml. Mission Control reads THAT FLAG, not the disk
# (bridge/app.py::status), so an install that skips this line shows "Not installed"
# forever — which is exactly how OpenCode shipped. The writer lives in ONE file that
# every component-shaped installer calls; see scripts/flip_installed.py.
"${PY:-python3}" "$ROOT/scripts/flip_installed.py" "$NAME" || {
  echo "[harness] ERROR: $NAME installed on disk but the harness.yaml flag could not be"
  echo "[harness]   set, so its card will still say 'Not installed'. Fix with:"
  echo "[harness]   python3 scripts/flip_installed.py $NAME"
  exit 1; }

echo "[harness] $NAME installed. Start it from the panel or scripts/start_component.sh $NAME"
