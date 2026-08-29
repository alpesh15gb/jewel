from __future__ import annotations

from pathlib import Path


BRIDGE = Path("jewel_tally_bridge/main.py")
TESTS = Path("tests/test_tally.py")


def patch_bridge() -> None:
    text = BRIDGE.read_text(encoding="utf-8")

    import_anchor = "import xml.etree.ElementTree as ET\n"
    compat_import = "from .xml_compat import parse_tally_xml\n"
    if compat_import not in text:
        if import_anchor not in text:
            raise RuntimeError("Could not find ElementTree import in Tally bridge")
        text = text.replace(import_anchor, import_anchor + "\n" + compat_import, 1)

    if "ET.fromstring(xml)" in text:
        count = text.count("ET.fromstring(xml)")
        if count != 3:
            raise RuntimeError(f"Expected 3 Tally response parsers, found {count}")
        text = text.replace("ET.fromstring(xml)", "parse_tally_xml(xml)")

    # Parent is not used by the bridge's ledger-name parser. Top-level Tally
    # ledgers can put the XML-illegal &#4; control marker in Parent, so do not
    # request that field in the first place.
    text = text.replace('    ET.SubElement(coll, "NATIVEMETHOD").text = "Parent"\n', "")

    BRIDGE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    old_import = "from jewel_tally_bridge.main import parse_daybook, parse_import_response\n"
    new_import = "from jewel_tally_bridge.main import parse_daybook, parse_import_response, parse_ledgers\n"
    if old_import in text:
        text = text.replace(old_import, new_import, 1)
    elif new_import not in text:
        raise RuntimeError("Could not update Tally parser test import")

    marker = "def test_tally_ledger_parser_tolerates_xml_illegal_control_references():"
    if marker not in text:
        text += '''\n\n\ndef test_tally_ledger_parser_tolerates_xml_illegal_control_references():\n    # TallyPrime can emit &#4; before the Parent of a top-level ledger. XML 1.0\n    # parsers reject that numeric reference even though the ledger name itself\n    # is perfectly usable. The bridge must tolerate the response.\n    xml = """<ENVELOPE><BODY><DATA>\n    <LEDGER NAME="Cash"><NAME>Cash</NAME><PARENT>&#4; Primary</PARENT></LEDGER>\n    <LEDGER NAME="શ્રી જ્વેલર્સ"><NAME>શ્રી જ્વેલર્સ</NAME><PARENT>Sundry Debtors</PARENT></LEDGER>\n    </DATA></BODY></ENVELOPE>"""\n    assert parse_ledgers(xml) == ["Cash", "શ્રી જ્વેલર્સ"]\n\n\ndef test_tally_parsers_tolerate_hex_control_reference_too():\n    parsed = parse_import_response(\n        "<ENVELOPE><BODY><DATA><DESC>Imported&#x4;OK</DESC><CREATED>1</CREATED><ERRORS>0</ERRORS></DATA></BODY></ENVELOPE>"\n    )\n    assert parsed["created"] == 1\n    assert parsed["errors"] == 0\n''' 

    TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_bridge()
    patch_tests()


if __name__ == "__main__":
    main()
