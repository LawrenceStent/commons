"""The real sales channels (P2.7), behind the same port as the fake ones (packs/storefront/channels.py). Every call
they make follows a request you approved at the gate; keys come from the environment (.env.example), never a save.

Etsy (Open API v3): full listing through the API.
    list       POST shops/{shop}/listings (a draft: type download, who_made i_did, when_made made_to_order), upload
               the PDF (files) and the cover (images), then PATCH state=active (Etsy charges its listing fee then)
    price      PUT listings/{id}/inventory (one offering)
    unlist     PATCH state=inactive
    sales      GET shops/{shop}/transactions, newest first, until one already seen
    taken down GET listings/{id}: gone, or in any state but active (draft too, once listings are activated)
    tokens     an OAuth access token lasts an hour; on a 401 it is refreshed with the refresh token and kept in
               runs/etsy-token.json (git-ignored), since Etsy rotates refresh tokens
    `draft_only=True` stops before activating: the first live step, to check everything at no cost

Lemon Squeezy: its API can't create or change products (they are read only), so listing there is manual. When you
approve, the store writes a kit (the PDF, the cover, the text) and tells you; you create the product in Lemon Squeezy
and link it (`commons link NAME P1 lemonsqueezy VARIANT_ID`). From then on its sales and refunds are read from the
orders API. Test mode first: a test-mode key only sees test orders. A linked variant that is gone or no longer
published counts as taken down.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path

from commons.adapters import secrets
from packs.storefront.channels import USD, Sale

Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]  # (method, url, headers, body)


class ChannelError(Exception):
    pass


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(5_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:4000]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ChannelError(f"couldn't reach {urllib.parse.urlsplit(url).hostname}: {e}") from e


def _multipart(fields: dict[str, str], name: str, filename: str, data: bytes, ctype: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
             for k, v in fields.items()]
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                 f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


class EtsyChannel:
    name, manual = "etsy", False
    API = "https://api.etsy.com/v3/application"
    TOKEN = "https://api.etsy.com/v3/public/oauth/token"

    def __init__(self, keystring: str, secret: str, shop: str, access: str, refresh: str, taxonomy: int,
                 transport: Transport = urllib_transport, token_file: Path | None = Path("runs/etsy-token.json"),
                 draft_only: bool = False):
        self.keystring, self.secret, self.shop, self.taxonomy = keystring, secret, shop, taxonomy
        self.access, self.refresh, self.transport, self.token_file, self.draft_only = access, refresh, transport, token_file, draft_only
        if token_file and token_file.exists():  # a refreshed pair from an earlier run wins over .env's
            saved = json.loads(token_file.read_text())
            self.access, self.refresh = saved.get("access", access), saved.get("refresh", refresh)
        self.seen: set[int] = set()

    @classmethod
    def from_env(cls, **kw) -> EtsyChannel | None:
        """From .env (see .env.example), or None if anything it needs is missing."""
        names = ("ETSY_KEYSTRING", "ETSY_SHOP_ID", "ETSY_ACCESS_TOKEN", "ETSY_TAXONOMY_ID")
        if secrets.missing(*names):
            return None
        g = secrets.get
        return cls(g("ETSY_KEYSTRING") or "", g("ETSY_SHARED_SECRET") or "", g("ETSY_SHOP_ID") or "",
                   g("ETSY_ACCESS_TOKEN") or "", g("ETSY_REFRESH_TOKEN") or "", int(g("ETSY_TAXONOMY_ID") or 0), **kw)

    def __getstate__(self) -> dict:  # a saved society keeps no keys: they come back from the environment on resume
        return {"seen": self.seen, "draft_only": self.draft_only}

    def __setstate__(self, state: dict) -> None:
        fresh = EtsyChannel.from_env(draft_only=state.get("draft_only", False))
        if fresh is None:
            raise ChannelError("the society has an Etsy channel but .env lacks its keys (see .env.example)")
        self.__dict__.update(fresh.__dict__, seen=state["seen"])

    # ── the port ───────────────────────────────────────────────
    def list(self, title, description, tags, price, quality, files=None) -> str:
        form = {"quantity": "999", "title": title, "description": description, "price": f"{price / USD:.2f}",
                "who_made": "i_did", "when_made": "made_to_order", "taxonomy_id": str(self.taxonomy),
                "type": "download", "is_supply": "false", "tags": ",".join(tags)}
        listing = str(self._call("POST", f"/shops/{self.shop}/listings", urllib.parse.urlencode(form).encode(),
                                 "application/x-www-form-urlencoded")["listing_id"])
        uploads = {"pdf": ("file", "application/pdf"), "pdf_a4": ("file", "application/pdf"), "cover": ("image", "image/png")}
        for kind, (field, ctype) in uploads.items():  # both paper sizes (Etsy allows five files), then the cover
            if files and kind in files:
                path = Path(files[kind])
                body, multipart = _multipart({"name": path.name} if field == "file" else {}, field, path.name,
                                             path.read_bytes(), ctype)
                self._call("POST", f"/shops/{self.shop}/listings/{listing}/{'files' if field == 'file' else 'images'}",
                           body, multipart)
        if not self.draft_only:
            self._state(listing, "active")
        return listing

    def set_price(self, listing: str, price: int) -> None:
        body = {"products": [{"sku": "", "property_values": [],
                              "offerings": [{"price": round(price / USD, 2), "quantity": 999, "is_enabled": True}]}]}
        self._call("PUT", f"/listings/{listing}/inventory", json.dumps(body).encode(), "application/json")

    def unlist(self, listing: str) -> None:
        self._state(listing, "inactive")

    @property
    def listing_fee(self) -> int:
        return 0 if self.draft_only else 200_000  # $0.20 when a listing goes active (again at each sale and renewal)

    def taken_down(self, listing: str) -> str | None:
        try:
            state = self._call("GET", f"/listings/{listing}").get("state", "")
        except ChannelError as e:
            return "Etsy no longer has the listing" if " 404 " in str(e) else None
        expected = ("active", "draft") if self.draft_only else ("active",)
        return None if state in expected else f"Etsy shows it as {state or 'unknown'}"

    def sales(self, cycle: int) -> list[Sale]:
        out = []
        for t in self._call("GET", f"/shops/{self.shop}/transactions?limit=100").get("results", []):
            tid = int(t["transaction_id"])
            if tid in self.seen:
                continue
            self.seen.add(tid)
            price = t["price"]
            gross = round(price["amount"] / price["divisor"] * int(t.get("quantity", 1)) * USD)
            out.append(Sale(str(t["listing_id"]), gross, round(gross * 0.095) + 450_000, cycle))  # Etsy's fees, est.
        return out

    def shop_info(self) -> dict:
        """The shop (read only): proves the keys and the token work."""
        return self._call("GET", f"/shops/{self.shop}")

    # ── plumbing ───────────────────────────────────────────────
    def _state(self, listing: str, state: str) -> None:
        self._call("PATCH", f"/shops/{self.shop}/listings/{listing}", urllib.parse.urlencode({"state": state}).encode(),
                   "application/x-www-form-urlencoded")

    def _call(self, method: str, path: str, body: bytes | None = None, ctype: str | None = None, retried=False) -> dict:
        headers = {"x-api-key": f"{self.keystring}:{self.secret}" if self.secret else self.keystring,
                   "Authorization": f"Bearer {self.access}", "Accept": "application/json"}
        if ctype:
            headers["Content-Type"] = ctype
        status, data = self.transport(method, self.API + path, headers, body)
        if status == 401 and not retried and self.refresh:
            self._refresh()
            return self._call(method, path, body, ctype, retried=True)
        if status >= 400:
            raise ChannelError(f"Etsy answered {status} to {method} {path.split('?')[0]}: {data[:300]!r}")
        return json.loads(data) if data else {}

    def _refresh(self) -> None:
        body = urllib.parse.urlencode({"grant_type": "refresh_token", "client_id": self.keystring,
                                       "refresh_token": self.refresh}).encode()
        status, data = self.transport("POST", self.TOKEN, {"Content-Type": "application/x-www-form-urlencoded"}, body)
        if status >= 400:
            raise ChannelError(f"Etsy wouldn't refresh the token ({status}); sign in again and update .env")
        tokens = json.loads(data)
        self.access, self.refresh = tokens["access_token"], tokens.get("refresh_token", self.refresh)
        if self.token_file:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(json.dumps({"access": self.access, "refresh": self.refresh}))


class LemonSqueezyChannel:
    name, manual, listing_fee = "lemonsqueezy", True, 0
    API = "https://api.lemonsqueezy.com/v1"

    def __init__(self, key: str, store: str, transport: Transport = urllib_transport):
        self.key, self.store, self.transport = key, store, transport
        self.linked: set[str] = set()  # variant ids you linked to products
        self.paid: set[str] = set()  # order ids booked as sales
        self.refunded: set[str] = set()

    @classmethod
    def from_env(cls, **kw) -> LemonSqueezyChannel | None:
        if secrets.missing("LEMONSQUEEZY_API_KEY", "LEMONSQUEEZY_STORE_ID"):
            return None
        return cls(secrets.get("LEMONSQUEEZY_API_KEY") or "", secrets.get("LEMONSQUEEZY_STORE_ID") or "", **kw)

    def __getstate__(self) -> dict:
        return {"linked": self.linked, "paid": self.paid, "refunded": self.refunded}

    def __setstate__(self, state: dict) -> None:
        fresh = LemonSqueezyChannel.from_env()
        if fresh is None:
            raise ChannelError("the society has a Lemon Squeezy channel but .env lacks its keys (see .env.example)")
        self.__dict__.update(fresh.__dict__, **state)

    def list(self, title, description, tags, price, quality, files=None) -> str:
        return ""  # no listing API: the store writes a kit, you create the product and link it

    def link(self, variant: str) -> None:
        self.linked.add(str(variant))

    def set_price(self, listing: str, price: int) -> None:
        pass  # by hand in Lemon Squeezy: the store tells you the new price

    def unlist(self, listing: str) -> None:
        self.linked.discard(listing)  # archive it by hand; its sales stop being collected

    def sales(self, cycle: int) -> list[Sale]:
        out = []
        for order in self._orders():
            a, oid = order["attributes"], str(order["id"])
            variant = str((a.get("first_order_item") or {}).get("variant_id", ""))
            if variant not in self.linked:
                continue
            gross = round(int(a.get("total", 0)) / 100 * USD)  # cents
            fee = round(gross * 0.05) + 500_000  # Lemon Squeezy's 5% + 50c, est.
            if a.get("status") == "paid" and oid not in self.paid:
                self.paid.add(oid)
                out.append(Sale(variant, gross, fee, cycle))
            elif a.get("status") == "refunded" and oid in self.paid and oid not in self.refunded:
                self.refunded.add(oid)
                out.append(Sale(variant, gross, fee, cycle, refund=True))
        return out

    def taken_down(self, listing: str) -> str | None:
        try:
            status, data = self.transport("GET", f"{self.API}/variants/{urllib.parse.quote(listing)}",
                                          {"Authorization": f"Bearer {self.key}", "Accept": "application/vnd.api+json"}, None)
        except ChannelError:
            return None
        if status == 404:
            return "Lemon Squeezy no longer has the product"
        if status >= 400:
            return None
        state = json.loads(data).get("data", {}).get("attributes", {}).get("status", "")
        return None if state == "published" else f"Lemon Squeezy shows it as {state or 'unknown'}"

    def order_count(self) -> int:
        """Orders visible to this key (read only): proves the key works (a test-mode key sees test orders)."""
        return len(self._orders())

    def _orders(self) -> list[dict]:
        url = f"{self.API}/orders?filter[store_id]={urllib.parse.quote(self.store)}&page[size]=100"
        status, data = self.transport("GET", url, {"Authorization": f"Bearer {self.key}",
                                                   "Accept": "application/vnd.api+json"}, None)
        if status >= 400:
            raise ChannelError(f"Lemon Squeezy answered {status}: {data[:300]!r}")
        return json.loads(data).get("data", [])

