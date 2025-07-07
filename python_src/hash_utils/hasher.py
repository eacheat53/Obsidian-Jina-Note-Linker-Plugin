"""Functions for extracting note content and computing SHA256 hashes."""
from __future__ import annotations

HASH_BOUNDARY_MARKER = "<!-- HASH_BOUNDARY -->"


def extract_content_for_hashing(text_body: str) -> str | None:
    """Return the part before HASH_BOUNDARY_MARKER (newline-normalised).
    If marker not found, return None.
    """
    idx = text_body.find(HASH_BOUNDARY_MARKER)
    if idx == -1:
        return None

    content = text_body[:idx]
    if not content.strip():
        return "\n"  # keep single newline for empty body

    # normalise line endings & trim trailing blanks
    content = content.replace("\r\n", "\n").rstrip() + "\n"
    return content


def calculate_hash_from_content(content: str) -> str:
    """SHA256 of given content (already normalised)."""
    import hashlib

    hasher = hashlib.sha256()
    hasher.update(content.encode("utf-8"))
    return hasher.hexdigest()
