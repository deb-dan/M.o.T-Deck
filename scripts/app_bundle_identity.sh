#!/usr/bin/env bash
# Shared installed-app identity resolver.
#
# Source this file; do not execute it.  The installed filename is not identity:
# Finder/user renames are allowed, while CFBundleIdentifier + the declared executable
# remain the contract.  Both shipping and component bootstrap use this exact predicate
# so a bundle one path accepts cannot silently be invisible to the other.

_harness_app_plist_value() {   # <bundle> <Info.plist key>
  /usr/libexec/PlistBuddy -c "Print :$2" "$1/Contents/Info.plist" 2>/dev/null || true
}

_harness_canonical_bundle_path() {   # <existing bundle directory>
  (cd -P "$1" 2>/dev/null && pwd -P)
}

_harness_valid_app() {   # <candidate bundle>
  local candidate="$1" bundle_id executable
  [[ -d "$candidate" && -f "$candidate/Contents/Info.plist" ]] || return 1
  bundle_id="$(_harness_app_plist_value "$candidate" CFBundleIdentifier)"
  [[ "$bundle_id" == "local.harness.app" ]] || return 1
  executable="$(_harness_app_plist_value "$candidate" CFBundleExecutable)"
  [[ "$executable" == "Harness" && -x "$candidate/Contents/MacOS/Harness" ]]
}

_harness_discover_app_bundles() { # <installation root>; NUL-delimited paths
  local root="$1"
  [[ -d "$root" ]] || return 0
  # Never descend into an app.  Include symlink-shaped aliases without following them;
  # validation and canonical-path deduplication happen in the resolver below.
  /usr/bin/find "$root" \( -type d -o -type l \) -name '*.app' -prune -print0 2>/dev/null
}

harness_resolve_installed_app() {
  # Usage:
  #   harness_resolve_installed_app
  #   harness_resolve_installed_app --roots ROOT...
  #   harness_resolve_installed_app --candidates APP...
  # Result is HARNESS_RESOLVED_APP. HARNESS_APP_PATH, when set, always wins and must
  # validate.  Zero/ambiguous discovery fails closed.  Set HARNESS_APP_RESOLVE_QUIET=1
  # for optional consumers that can proceed without a bundled app resource.
  local mode="roots" candidate install_root seen existing
  local explicit=0
  local -a inputs=() candidates=() valid=()
  HARNESS_RESOLVED_APP=""

  if [[ -n "${HARNESS_APP_PATH:-}" ]]; then
    explicit=1
    candidates=("$HARNESS_APP_PATH")
  else
    if [[ "${1:-}" == "--roots" || "${1:-}" == "--candidates" ]]; then
      mode="${1#--}"
      shift
    fi
    inputs=("$@")
    if [[ "$mode" == "candidates" ]]; then
      candidates=("${inputs[@]:-}")
    else
      [[ ${#inputs[@]} -gt 0 ]] || inputs=(/Applications "$HOME/Applications")
      for install_root in "${inputs[@]}"; do
        while IFS= read -r -d '' candidate; do
          candidates+=("$candidate")
        done < <(_harness_discover_app_bundles "$install_root")
      done
    fi
  fi

  for candidate in "${candidates[@]}"; do
    _harness_valid_app "$candidate" || continue
    candidate="$(_harness_canonical_bundle_path "$candidate")" || continue
    seen=0
    for existing in "${valid[@]:-}"; do
      [[ "$existing" == "$candidate" ]] && { seen=1; break; }
    done
    [[ "$seen" -eq 1 ]] || valid+=("$candidate")
  done

  if [[ "$explicit" -eq 1 && ${#valid[@]} -eq 0 ]]; then
    if [[ "${HARNESS_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]} ERROR: HARNESS_APP_PATH '$HARNESS_APP_PATH' is not a valid Harness bundle."
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]}        It must have CFBundleIdentifier local.harness.app and"
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]}        CFBundleExecutable Harness at Contents/MacOS/Harness (executable)."
    fi
    return 2
  fi
  if [[ ${#valid[@]} -eq 0 ]]; then
    if [[ "${HARNESS_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]} ERROR: no valid installed Harness bundle found under the selected application roots."
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]}        Set HARNESS_APP_PATH to an explicit valid bundle path to override."
    fi
    return 3
  fi
  if [[ "$explicit" -eq 0 && ${#valid[@]} -gt 1 ]]; then
    if [[ "${HARNESS_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]} ERROR: more than one valid Harness bundle was found; refusing to guess:"
      for candidate in "${valid[@]}"; do
        echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]}        $candidate"
      done
      echo "${HARNESS_APP_RESOLVE_PREFIX:-[harness]}        Set HARNESS_APP_PATH to the installed bundle that owns your running app."
    fi
    return 4
  fi

  HARNESS_RESOLVED_APP="${valid[0]}"
}
