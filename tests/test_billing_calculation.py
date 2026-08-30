from jewel_server.services import calculate_item_price, quote_sale
from jewel_client.billing_page import line_formula
import run_client


SCREENSHOT_ITEM = {
    "id": 1,
    "tag_no": "TAG-0000001",
    "name": "Ornate Ring",
    "metal": "Gold",
    "purity": "916",
    "gross_weight": 4.000,
    "net_weight": 3.765,
    "wastage_percent": 9,
    "making_type": "fixed",
    "making_value": 7530,
    "stone_value": 5000,
    "gst_rate": 3,
    "cost_amount": 0,
    "status": "in_stock",
}


class _Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _OneItemConn:
    def __init__(self, item):
        self.item = item

    def execute(self, sql, params=()):
        assert "FROM items WHERE id" in sql
        assert int(params[0]) == int(self.item["id"])
        return _Result(self.item)


def test_screenshot_item_price_exposes_wastage_component():
    price = calculate_item_price(None, SCREENSHOT_ITEM, {"metal_rate": 14550})
    assert price["metal_value"] == 54780.75
    assert price["wastage_percent"] == 9.0
    assert price["wastage_value"] == 4930.27
    assert price["making_charge"] == 7530.0
    assert price["stone_value"] == 5000.0
    assert price["taxable"] == 72241.02
    assert price["gst_amount"] == 2167.23
    assert price["line_total"] == 74408.25


def test_invoice_discount_requotes_taxable_gst_and_roundoff():
    conn = _OneItemConn(SCREENSHOT_ITEM)
    quote = quote_sale(
        conn,
        [{"item_id": 1, "metal_rate": 14550}],
        header_discount=1000,
        old_gold_value=0,
    )
    assert quote["subtotal"] == 72241.02
    assert quote["discount"] == 1000.0
    assert quote["taxable"] == 71241.02
    assert quote["gst"] == 2137.23
    assert quote["round_off"] == -0.25
    assert quote["total"] == 73378.0
    assert quote["payable"] == 73378.0
    assert quote["lines"][0]["discount"] == 1000.0
    assert quote["lines"][0]["line_total"] == 73378.25


def test_ui_formula_names_every_visible_price_component():
    price = calculate_item_price(None, SCREENSHOT_ITEM, {"metal_rate": 14550})
    text = line_formula(price)
    assert "3.765 g" in text
    assert "₹14,550.00/g" in text
    assert "Wastage 9.00%" in text
    assert "₹4,930.27" in text
    assert "Making ₹7,530.00" in text
    assert "Stones ₹5,000.00" in text
    assert "GST 3.00% ₹2,167.23" in text
    assert "₹74,408.25" in text


def test_client_entrypoint_registers_enhanced_billing_page():
    main_module = run_client._install_enhanced_billing_page()
    assert main_module.POSPage.__module__ == "jewel_client.billing_page"
