#!/usr/bin/env bash
# Shared installed-app identity resolver.
#
# Source this file; do not execute it.  The installed filename is not identity:
# Finder/user renames are allowed, while CFBundleIdentifier + the declared executable
# remain the contract.  Both shipping and component bootstrap use this exact predicate
# so a bundle one path accepts cannot silently be invisible to the other.

_motdeck_app_plist_value() {   # <bundle> <Info.plist key>
  /usr/libexec/PlistBuddy -c "Print :$2" "$1/Contents/Info.plist" 2>/dev/null || true
}

_motdeck_canonical_bundle_path() {   # <existing bundle directory>
  (cd -P "$1" 2>/dev/null && pwd -P)
}

_motdeck_valid_app() {   # <candidate bundle>
  local candidate="$1" bundle_id executable
  [[ -d "$candidate" && -f "$candidate/Contents/Info.plist" ]] || return 1
  bundle_id="$(_motdeck_app_plist_value "$candidate" CFBundleIdentifier)"
  [[ "$bundle_id" == "local.motdeck.app" ]] || return 1
  executable="$(_motdeck_app_plist_value "$candidate" CFBundleExecutable)"
  [[ "$executable" == "MOTDeck" && -x "$candidate/Contents/MacOS/MOTDeck" ]]
}

_motdeck_discover_app_bundles() { # <installation root>; NUL-delimited paths
  local root="$1"
  [[ -d "$root" ]] || return 0
  # Never descend into an app.  Include symlink-shaped aliases without following them;
  # validation and canonical-path deduplication happen in the resolver below.
  /usr/bin/find "$root" \( -type d -o -type l \) -name '*.app' -prune -print0 2>/dev/null
}

motdeck_resolve_installed_app() {
  # Usage:
  #   motdeck_resolve_installed_app
  #   motdeck_resolve_installed_app --roots ROOT...
  #   motdeck_resolve_installed_app --candidates APP...
  # Result is MOT_DECK_RESOLVED_APP. MOT_DECK_APP_PATH, when set, always wins and must
  # validate.  Zero/ambiguous discovery fails closed.  Set MOT_DECK_APP_RESOLVE_QUIET=1
  # for optional consumers that can proceed without a bundled app resource.
  local mode="roots" candidate install_root seen existing
  local explicit=0
  local -a inputs=() candidates=() valid=()
  MOT_DECK_RESOLVED_APP=""

  if [[ -n "${MOT_DECK_APP_PATH:-}" ]]; then
    explicit=1
    candidates=("$MOT_DECK_APP_PATH")
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
        done < <(_motdeck_discover_app_bundles "$install_root")
      done
    fi
  fi

  for candidate in "${candidates[@]}"; do
    _motdeck_valid_app "$candidate" || continue
    candidate="$(_motdeck_canonical_bundle_path "$candidate")" || continue
    seen=0
    for existing in "${valid[@]:-}"; do
      [[ "$existing" == "$candidate" ]] && { seen=1; break; }
    done
    [[ "$seen" -eq 1 ]] || valid+=("$candidate")
  done

  if [[ "$explicit" -eq 1 && ${#valid[@]} -eq 0 ]]; then
    if [[ "${MOT_DECK_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]} ERROR: MOT_DECK_APP_PATH '$MOT_DECK_APP_PATH' is not a valid MOT Deck bundle."
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]}        It must have CFBundleIdentifier local.motdeck.app and"
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]}        CFBundleExecutable MOTDeck at Contents/MacOS/MOTDeck (executable)."
    fi
    return 2
  fi
  if [[ ${#valid[@]} -eq 0 ]]; then
    if [[ "${MOT_DECK_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]} ERROR: no valid installed MOT Deck bundle found under the selected application roots."
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]}        Set MOT_DECK_APP_PATH to an explicit valid bundle path to override."
    fi
    return 3
  fi
  if [[ "$explicit" -eq 0 && ${#valid[@]} -gt 1 ]]; then
    if [[ "${MOT_DECK_APP_RESOLVE_QUIET:-0}" != "1" ]]; then
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]} ERROR: more than one valid MOT Deck bundle was found; refusing to guess:"
      for candidate in "${valid[@]}"; do
        echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]}        $candidate"
      done
      echo "${MOT_DECK_APP_RESOLVE_PREFIX:-[motdeck]}        Set MOT_DECK_APP_PATH to the installed bundle that owns your running app."
    fi
    return 4
  fi

  MOT_DECK_RESOLVED_APP="${valid[0]}"
}
