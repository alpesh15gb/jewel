import xml.etree.ElementTree as ET

from jewel_server.tally import build_voucher_xml, stable_remote_id
from jewel_tally_bridge.main import parse_daybook, parse_import_response


def test_tally_voucher_xml_is_balanced_and_has_remote_id():
    rid = stable_remote_id("sale", 42)
    xml = build_voucher_xml(
        company="Demo Jewellers",
        voucher_type="Sales",
        voucher_number="INV-42",
        date="20260829",
        remote_id=rid,
        narration="test",
        entries=[
            {"ledger": "Cash", "amount": 103.00, "debit": True},
            {"ledger": "Jewellery Sales", "amount": 100.00, "debit": False},
            {"ledger": "Output CGST", "amount": 1.50, "debit": False},
            {"ledger": "Output SGST", "amount": 1.50, "debit": False},
        ],
    )
    root = ET.fromstring(xml)
    voucher = root.find(".//VOUCHER")
    assert voucher is not None
    assert voucher.attrib["REMOTEID"] == rid
    assert root.findtext(".//VOUCHERNUMBER") == "INV-42"


def test_tally_import_response_parser():
    parsed = parse_import_response("""<ENVELOPE><BODY><DATA><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS><LASTVCHID>88</LASTVCHID><VCHNUMBER>INV-1</VCHNUMBER></DATA></BODY></ENVELOPE>""")
    assert parsed["created"] == 1
    assert parsed["errors"] == 0
    assert parsed["last_vch_id"] == 88
    assert parsed["voucher_number"] == "INV-1"


def test_daybook_parser_reads_accounting_voucher_amount():
    xml = """<ENVELOPE><BODY><DATA><VOUCHER REMOTEID="abc"><DATE>20260829</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME><VOUCHERNUMBER>INV-1</VOUCHERNUMBER><ALLLEDGERENTRIES.LIST><LEDGERNAME>Cash</LEDGERNAME><AMOUNT>-103.00</AMOUNT></ALLLEDGERENTRIES.LIST><ALLLEDGERENTRIES.LIST><LEDGERNAME>Sales</LEDGERNAME><AMOUNT>100.00</AMOUNT></ALLLEDGERENTRIES.LIST><ALLLEDGERENTRIES.LIST><LEDGERNAME>GST</LEDGERNAME><AMOUNT>3.00</AMOUNT></ALLLEDGERENTRIES.LIST></VOUCHER></DATA></BODY></ENVELOPE>"""
    rows = parse_daybook(xml)
    assert rows == [{"number": "INV-1", "type": "Sales", "date": "20260829", "remote_id": "abc", "master_id": "", "amount": 103.0}]
