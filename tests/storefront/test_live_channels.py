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
    assert steps == [("POST", "/shops/shop1/listings"), ("POST", "/shops/shop1/listings/777/files"),
                     ("POST", "/shops/shop1/listings/777/images"), ("PATCH", "/shops/shop1/listings/777")]
    form = calls[0][3].decode()
    assert "type=download" in form and "price=4.99" in form and "who_made=i_did" in form and "taxonomy_id=2078" in form
    assert calls[0][2]["x-api-key"] == "key:secret" and b"state=active" in calls[3][3]


def test_etsy_draft_only_stops_before_activating(tmp_path):
    transport, calls = etsy_fake()
    ch = EtsyChannel("key", "", "shop1", "old", "r", 1, transport=transport, token_file=None, draft_only=True)
    ch.list("A", "B", ("t",), USD * 5, 1.0)
    assert [m for m, *_ in calls] == ["POST"]


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
