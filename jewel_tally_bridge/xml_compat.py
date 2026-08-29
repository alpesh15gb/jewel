from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# TallyPrime can emit XML 1.0-illegal numeric character references such as
# ``&#4;`` in internal fields (notably the Parent value of top-level ledgers).
# Strict XML parsers reject the entire response before useful data can be read.
_NUMERIC_CHAR_REF = re.compile(r"&#(?:[xX]([0-9A-Fa-f]+)|([0-9]+));")


def _xml10_allowed(codepoint: int) -> bool:
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def sanitize_tally_xml(text: str) -> str:
    """Return XML that a strict XML 1.0 parser can consume.

    Only XML-illegal numeric references and literal XML-illegal code points are
    removed. Valid Unicode, entity references, Indian-language text and normal
    XML whitespace are preserved.
    """

    def replace_ref(match: re.Match[str]) -> str:
        raw = match.group(1) or match.group(2)
        base = 16 if match.group(1) is not None else 10
        try:
            codepoint = int(raw, base)
        except ValueError:
            return match.group(0)
        return match.group(0) if _xml10_allowed(codepoint) else ""

    cleaned = _NUMERIC_CHAR_REF.sub(replace_ref, text)
    return "".join(ch for ch in cleaned if _xml10_allowed(ord(ch)))


def parse_tally_xml(text: str) -> ET.Element:
    return ET.fromstring(sanitize_tally_xml(text))
