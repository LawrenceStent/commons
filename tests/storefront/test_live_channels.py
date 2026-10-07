"""P2.7: the real channels against fake transports (no network, no fees). Etsy lists by API (draft, files, activate),
reprices, unlists and reads transactions, refreshing its token on a 401. Lemon Squeezy can't list by API: approving
writes a kit, you link the product, and its orders (and refunds) are read from then on."""

import json
import pickle

import pytest

from packs.storefront.channels import USD
from packs.storefront.live_channels import ChannelError, EtsyChannel, LemonSqueezyChannel


def etsy_fake(expire_first=False):
    calls, state = [], {"expired": expire_first}

    def transport(method, url, headers, body):
        calls.append((method, url.split("/application")[-1].split("?")[0] if "/application" in url else url, headers, body))
        if "oauth/token" in url:
            return 200, json.dumps({"access_token": "new-access", "refresh_token": "new-refresh"}).encode()
        if state["expired"] and headers.get("Authorization") == "Bearer old":
            return 401, b"expired"
        if method == "POST" and url.endswith("/listings"):
            return 201, json.dumps({"listing_id": 777}).encode()
        if method == "GET" and "/transactions" in url:
            return 200, json.dumps({"results": [{"transaction_id": 1, "listing_id": 777, "quantity": 1,
                                                 "price": {"amount": 499, "divisor": 100}}]}).encode()
        return 200, b"{}"
    return transport, calls


def etsy(tmp_path, **kw):
    transport, calls = etsy_fake(**kw)
    return EtsyChannel("key", "secret", "shop1", "old", "refresh", 2078, transport=transport,
                       token_file=tmp_path / "etsy.json"), calls


def test_etsy_lists_a_digital_draft_uploads_its_files_and_activates_it(tmp_path):
    (tmp_path / "p.pdf").write_bytes(b"%PDF-1")
    (tmp_path / "c.png").write_bytes(b"PNG")
    ch, calls = etsy(tmp_path)
    listing = ch.list("A Plan", "Thirty days.", ("bible", "kjv"), round(4.99 * USD), 0.9,
                      {"pdf": tmp_path / "p.pdf", "cover": tmp_path / "c.png"})
    assert listing == "777"
    steps = [(m, path) for m, path, _, _ in calls]
    assert steps == [("GET", "/shops/shop1"), ("POST", "/shops/shop1/listings"), ("POST", "/shops/shop1/listings/777/files"),
                     ("POST", "/shops/shop1/listings/777/images"), ("PATCH", "/shops/shop1/listings/777")]
    form = calls[1][3].decode()
    assert "type=download" in form and "price=4.99" in form and "who_made=i_did" in form and "taxonomy_id=2078" in form
    assert calls[1][2]["x-api-key"] == "key:secret" and b"state=active" in calls[4][3]


def test_etsy_draft_only_stops_before_activating(tmp_path):
    transport, calls = etsy_fake()
    ch = EtsyChannel("key", "", "shop1", "old", "r", 1, transport=transport, token_file=None, draft_only=True)
    ch.list("A", "B", ("t",), USD * 5, 1.0)
    assert [m for m, *_ in calls] == ["GET", "POST"]  # the shop's currency, then the draft


def test_etsy_refreshes_an_expired_token_and_keeps_the_new_pair(tmp_path):
    ch, calls = etsy(tmp_path, expire_first=True)
    ch.unlist("777")
    assert ch.access == "new-access" and json.loads((tmp_path / "etsy.json").read_text())["refresh"] == "new-refresh"
    assert calls[-1][2]["Authorization"] == "Bearer new-access"


def test_etsy_reads_each_transaction_once_and_reprices_through_inventory(tmp_path):
    ch, calls = etsy(tmp_path)
    sales = ch.sales(5)
    assert len(sales) == 1 and sales[0].listing == "777" and sales[0].gross == round(4.99 * USD)
    assert ch.sales(6) == []
    ch.set_price("777", round(6.5 * USD))
    assert calls[-1][0] == "PUT" and json.loads(calls[-1][3])["products"][0]["offerings"][0]["price"] == 6.5


def test_etsy_errors_are_readable(tmp_path):
    ch = EtsyChannel("k", "", "s", "a", "", 1, transport=lambda *a: (403, b"forbidden"), token_file=None)
    with pytest.raises(ChannelError, match="403"):
        ch.unlist("1")


def lemon(orders):
    def transport(method, url, headers, body):
        assert "filter[store_id]=store9" in url and headers["Authorization"] == "Bearer ls-key"
        return 200, json.dumps({"data": orders()}).encode()
    return LemonSqueezyChannel("ls-key", "store9", transport=transport)


def order(oid, status, variant="v1", total=499):
    return {"id": oid, "attributes": {"status": status, "total": total, "first_order_item": {"variant_id": variant}}}


def test_lemon_squeezy_lists_by_hand_and_reads_linked_orders_and_refunds():
    now = {"orders": [order("o1", "paid"), order("o2", "paid", variant="other")]}
    ch = lemon(lambda: now["orders"])
    assert ch.manual and ch.list("A", "B", (), USD, 1.0) == ""
    assert ch.sales(1) == []  # nothing linked yet
    ch.link("v1")
    sales = ch.sales(2)
    assert [(s.listing, s.gross, s.refund) for s in sales] == [("v1", round(4.99 * USD), False)]
    assert ch.sales(3) == []
    now["orders"] = [order("o1", "refunded")]
    assert [s.refund for s in ch.sales(4)] == [True]


def test_a_saved_channel_keeps_no_keys_and_needs_them_back_from_the_environment(tmp_path, monkeypatch):
    ch, _ = etsy(tmp_path)
    for name in ("ETSY_KEYSTRING", "ETSY_SHOP_ID", "ETSY_ACCESS_TOKEN", "ETSY_TAXONOMY_ID"):
        monkeypatch.delenv(name, raising=False)
    data = pickle.dumps(ch)
    assert b"secret" not in data and b"old" not in data
    with pytest.raises(ChannelError, match="lacks its keys"):
        pickle.loads(data)
    monkeypatch.setenv("ETSY_KEYSTRING", "k2")
    monkeypatch.setenv("ETSY_SHOP_ID", "shop2")
    monkeypatch.setenv("ETSY_ACCESS_TOKEN", "a2")
    monkeypatch.setenv("ETSY_TAXONOMY_ID", "5")
    monkeypatch.chdir(tmp_path)
    back = pickle.loads(data)
    assert back.shop == "shop2" and back.taxonomy == 5


def test_etsy_sign_in_uses_pkce_and_swaps_the_code_for_tokens():
    import base64
    import hashlib
    import urllib.parse

    from packs.storefront import etsy_login

    url = etsy_login.authorize_url("key", "st", "verifier-123")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    expected = base64.urlsafe_b64encode(hashlib.sha256(b"verifier-123").digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == [expected] and q["code_challenge_method"] == ["S256"] and q["client_id"] == ["key"]
    assert q["scope"] == ["listings_r listings_w transactions_r"] and q["redirect_uri"] == [etsy_login.REDIRECT]
    sent = {}

    def transport(method, url, headers, body):
        sent.update(urllib.parse.parse_qs(body.decode()))
        return 200, json.dumps({"access_token": "a", "refresh_token": "r"}).encode()

    assert etsy_login.exchange("key", "code-1", "verifier-123", transport) == {"access_token": "a", "refresh_token": "r"}
    assert sent["grant_type"] == ["authorization_code"] and sent["code_verifier"] == ["verifier-123"]


def answering(status, body):
    return lambda method, url, headers, data: (status, json.dumps(body).encode() if body is not None else b"gone")


def test_etsy_reports_a_listing_it_took_down_and_charges_a_fee_only_when_activating():
    def ch(status, body, draft_only=False):
        return EtsyChannel("k", "", "s", "a", "", 1, transport=answering(status, body), token_file=None, draft_only=draft_only)
    assert ch(200, {"state": "active"}).taken_down("777") is None
    assert "removed" in ch(200, {"state": "removed"}).taken_down("777")
    assert "no longer has" in ch(404, None).taken_down("777")
    assert ch(500, None).taken_down("777") is None  # unreachable isn't a takedown
    assert ch(200, {"state": "draft"}, draft_only=True).taken_down("777") is None
    assert ch(200, {}).listing_fee == 200_000 and ch(200, {}, draft_only=True).listing_fee == 0


def test_lemon_squeezy_reports_a_variant_gone_or_unpublished():
    def ch(status, body):
        return LemonSqueezyChannel("key", "1", transport=answering(status, body))
    assert ch(200, {"data": {"attributes": {"status": "published"}}}).taken_down("42") is None
    assert "draft" in ch(200, {"data": {"attributes": {"status": "draft"}}}).taken_down("42")
    assert "no longer has" in ch(404, None).taken_down("42")


def gbp_shop(currency_code="GBP", rate=0.75):
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url, body))
        if method == "GET" and url.endswith("/shops/shop1"):
            return 200, json.dumps({"currency_code": currency_code}).encode()
        if method == "POST" and url.endswith("/listings"):
            return 201, json.dumps({"listing_id": 9}).encode()
        if "/transactions" in url:
            return 200, json.dumps({"results": [{"transaction_id": 5, "listing_id": 9, "quantity": 1,
                                                 "price": {"amount": 600, "divisor": 100, "currency_code": "GBP"}}]}).encode()
        return 200, b"{}"
    ch = EtsyChannel("k", "", "shop1", "a", "", 1, transport=transport, token_file=None, draft_only=True,
                     currency="GBP", rate=rate, fees="uk")
    return ch, calls


def test_a_uk_shop_lists_in_pounds_and_its_sales_come_back_in_dollars():
    ch, calls = gbp_shop()
    ch.list("A", "B", ("t",), round(7.99 * USD), 1.0)
    assert b"price=5.99" in calls[1][2]  # $7.99 at 0.75 to the dollar
    ch.set_price("9", 10 * USD)
    assert b'"price": 7.5' in calls[-1][2]
    sale = ch.sales(1)[0]
    assert sale.gross == 8 * USD  # £6.00 is $8.00
    assert sale.fee == round(8 * USD * (0.065 + 0.04 + 0.0048) + 0.20 / 0.75 * USD) + 200_000


def test_a_shop_in_another_currency_is_refused_before_anything_is_listed():
    ch, calls = gbp_shop(currency_code="GBP")
    ch.currency, ch.rate = "USD", 1.0  # .env says USD, the shop says GBP
    with pytest.raises(ChannelError, match="sells in GBP"):
        ch.list("A", "B", ("t",), 5 * USD, 1.0)
    assert [m for m, *_ in calls] == ["GET"]
    no_rate, _ = gbp_shop(rate=None)
    with pytest.raises(ChannelError, match="ETSY_USD_RATE"):
        no_rate.list("A", "B", ("t",), 5 * USD, 1.0)
