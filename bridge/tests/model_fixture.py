"""Small binary model fixtures that follow the real published file structures.

Centralizing these prevents a test from making a magic prefix look like a model—the
exact shortcut U83 exists to remove.
"""
from __future__ import annotations

import json
import struct


def gguf_bytes(*, version: int = 3, tensor_offset: int = 0,
               tensor_type: int = 0) -> bytes:
    """One metadata entry, one F32 tensor descriptor, and one F32 payload."""
    if version not in (2, 3):
        # The application accepts v1, but new fixtures exercise the current u64-count
        # grammar. Dedicated malformed-version tests still cover rejection.
        raise ValueError("fixture supports GGUF v2/v3")

    def string(value: str) -> bytes:
        raw = value.encode("utf-8")
        return struct.pack("<Q", len(raw)) + raw

    out = bytearray(b"GGUF" + struct.pack("<IQQ", version, 1, 1))
    out += string("general.architecture") + struct.pack("<I", 8) + string("unit")
    out += string("weight") + struct.pack("<I", 1) + struct.pack("<Q", 1)
    out += struct.pack("<I", tensor_type) + struct.pack("<Q", tensor_offset)
    out += b"\0" * ((-len(out)) % 32)
    out += b"\0\0\0\0"
    return bytes(out)


def safetensors_bytes(*, dtype: str = "F32", shape=(1,), payload_bytes: int = 4) -> bytes:
    """One tensor whose declared interval exactly covers its payload.

    Callers choose the shape and payload length explicitly for packed dtypes.  The
    fixture does not duplicate the production dtype-width table, so a production
    mistake cannot make its own test data silently agree with it.
    """
    header = json.dumps({"weight": {
        "dtype": dtype, "shape": list(shape), "data_offsets": [0, payload_bytes],
    }}, separators=(",", ":")).encode()
    return struct.pack("<Q", len(header)) + header + b"\0" * payload_bytes
