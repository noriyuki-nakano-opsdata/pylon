"""Input sanitization based on trust levels.

Applies progressive sanitization:
- trusted: no sanitization
- internal: control character removal
- untrusted: full sanitization (HTML/script, control chars, length limit)
"""

from __future__ import annotations

import re

from pylon.types import TrustLevel

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

DEFAULT_MAX_LENGTH = 100_000


class InputSanitizer:
    """Trust-level-based input sanitization."""

    def __init__(self, *, max_length: int = DEFAULT_MAX_LENGTH) -> None:
        self._max_length = max_length

    def sanitize(self, text: str, trust_level: TrustLevel) -> str:
        """Sanitize input based on trust level.

        - TRUSTED: no changes
        - INTERNAL: strip control characters
        - UNTRUSTED: strip HTML/script tags, control chars, enforce length limit
        """
        if trust_level == TrustLevel.TRUSTED:
            return text

        if trust_level == TrustLevel.INTERNAL:
            return self._strip_control_chars(text)

        # UNTRUSTED: full sanitization
        result = self._strip_scripts(text)
        result = self._strip_html_tags(result)
        result = self._strip_control_chars(result)
        result = self._enforce_length(result)
        return result

    def _strip_scripts(self, text: str) -> str:
        return _SCRIPT_BLOCK_RE.sub("", text)

    def _strip_html_tags(self, text: str) -> str:
        return _HTML_TAG_RE.sub("", text)

    def _strip_control_chars(self, text: str) -> str:
        return _CONTROL_CHAR_RE.sub("", text)

    def _enforce_length(self, text: str) -> str:
        if len(text) > self._max_length:
            return text[: self._max_length]
        return text
