"""Shared validation for the panel's non-image Agent/Hermes attachment lane.

Images retain their existing, vision-aware path.  This module owns the deliberately
smaller cross-backend document contract: every accepted suffix is supported by both
Odysseus chat uploads and Hermes ``file.attach``/``pdf.attach`` at the pinned versions.
"""
from __future__ import annotations

import base64
import binascii
import os


CHAT_FILE_MAX_BYTES = 10 * 1024 * 1024
CHAT_FILE_SUFFIXES = frozenset({
    ".csv", ".html", ".js", ".json", ".md", ".pdf", ".py", ".txt",
})


def decode_chat_file(data_url, name, mime="") -> tuple[dict | None, str]:
    """Return a validated attachment record and ``""``, or ``None`` and a reason.

    The 10 MiB ceiling mirrors Odysseus's default chat-upload contract, the narrower
    of the two backends.  Filename membership is authoritative here; a browser MIME
    is advisory and is never allowed to widen the suffix set.
    """
    if not data_url:
        return None, ""
    if not isinstance(data_url, str) or not data_url.startswith("data:"):
        return None, "attachment is not a base64 data URL — attach removed"
    # Keep the user-facing basename, but never pass control characters into either
    # upstream's multipart/RPC filename fields. A suffix is still required below, so
    # stripping a hostile name cannot silently manufacture a generic attachment.
    supplied_name = os.path.basename(str(name or "").strip())
    clean_name = "".join(ch for ch in supplied_name
                         if ch >= " " and ch != "\x7f")[:200]
    suffix = os.path.splitext(clean_name.lower())[1]
    if suffix not in CHAT_FILE_SUFFIXES:
        kinds = "txt / md / csv / json / py / js / html / pdf"
        return None, f"unsupported file type — choose {kinds}"
    head, comma, payload = data_url.partition(",")
    if not comma or not head.lower().endswith(";base64"):
        return None, "attachment is not a base64 data URL — attach removed"
    try:
        raw = base64.b64decode("".join(payload.split()), validate=True)
    except (ValueError, binascii.Error):
        return None, "attachment data could not be decoded — attach removed"
    if not raw:
        return None, "attachment is empty — attach removed"
    if len(raw) > CHAT_FILE_MAX_BYTES:
        return None, "file too large (max 10 MB) — attach removed"
    declared = head[5:-len(";base64")].split(";", 1)[0].strip().lower()
    return {
        "data_url": data_url,
        "name": clean_name,
        "mime": str(mime or declared or "application/octet-stream")[:200],
        "raw": raw,
        "kind": "pdf" if suffix == ".pdf" else "file",
    }, ""


async def stage_hermes_attachment(rpc, sid: str, image: str, image_name: str,
                                  chat_file: dict | None) -> tuple[str, str]:
    """Stage one validated attachment through the pinned Hermes RPC contract.

    Returns ``(error, prompt_suffix)``. Generic files need their returned ``@file``
    reference appended to the prompt; images and rendered PDFs are queued natively.
    """
    if not image and not chat_file:
        return "", ""
    try:
        if image:
            result = await rpc("image.attach_bytes", {
                "session_id": sid, "content_base64": image,
                "filename": image_name or "image.png"})
            suffix = ""
        elif chat_file["kind"] == "pdf":
            result = await rpc("pdf.attach", {
                "session_id": sid, "content_base64": chat_file["data_url"],
                "filename": chat_file["name"]})
            suffix = ""
        else:
            result = await rpc("file.attach", {
                "session_id": sid, "data_url": chat_file["data_url"],
                "name": chat_file["name"]})
            suffix = str((result or {}).get("ref_text") or "")
    except Exception as exc:  # noqa: BLE001 — the RPC reason is user-visible
        return f"Hermes refused the attachment: {str(exc)[:180]}", ""
    if not (result or {}).get("attached"):
        return "Hermes did not attach the file (no reason given)", ""
    return "", suffix
