"""The store: products made by the society, listed on channels only with your approval, and their sales.

    a product        every paid product job becomes a draft product: its listing part gives the title,
                     description, tags and price; the maker is the job's prime
    list_product     the maker asks to list it on one or more channels (combinations); the listing is checked
                     (Etsy's limits, the price range, the storefront's rules) and goes to the gate as a publish
                     request carrying everything that would go public. Nothing is listed until you approve
    set_price        a new price, through the gate the same way
    drop_product     unlisting, through the gate the same way (your decision, 5 Oct: dropping needs you)
    kill criteria    a listed product with no sale for `drop_after` cycles raises a drop request; it is still you
                     who decides
    sales            collected from every channel each cycle and paid to the maker, after the channel's fee, by the
                     ledger's revenue rule; `credit_per_dollar` scales dollars to the society's money (1:1 in a
                     live society; scaled down for simulated credits)
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from commons.application.screening import screen
from commons.substrate.ledger import purse
from packs.storefront import files
from packs.storefront.channels import USD, Channel

MAX_TITLE, MAX_TAGS, MAX_TAG = 140, 13, 20
PRICES = (5.00, 49.99)  # your floor (6 Oct): $5, so channel fees stay small; aim well above with bundles and packs


class Stage(StrEnum):
    DRAFT = "draft"
    REQUESTED = "requested"  # waiting for your decision on a listing
    LISTED = "listed"
    DROPPED = "dropped"


@dataclass
class Product:
    id: str
    job: str
    maker: str
    title: str
    description: str
    tags: tuple[str, ...]
    price: int  # µ$
    quality: float  # the job's mean grade
    stage: Stage = Stage.DRAFT
    listings: dict[str, str] = field(default_factory=dict)  # channel -> listing id
    wanted: dict = field(default_factory=dict)  # what a pending request asked for (channels, price)
    listed_at: int | None = None
    last_sale: int | None = None
    sold: int = 0
    revenue: int = 0  # µ$ gross
    content: str = ""  # the product itself (its content part), for the PDF
    files: dict = field(default_factory=dict)  # pdf, cover: paths, written when a listing is requested
    art: str = ""  # an approved illustration (a path), for the cover
    art_prompt: str = ""  # what an illustration request asked for
    parts: tuple[str, ...] = ()  # a bundle: the products it's made of


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "why": {"type": "string", "description": "optional: why"}},
            "required": required, "additionalProperties": False}


S, N = {"type": "string"}, {"type": "number"}
BUNDLE = (2, 6)  # products in a bundle
ASSEMBLER = 0.15  # of a bundle's sales, to the co-op that put it together; the rest to its parts' makers, by price

TOOLS = (
    {"name": "drop_product", "description": "Ask the operator to unlist one of your products everywhere. Free; waits "
     "for their approval.", "input_schema": _schema({"product_id": S, "reason": S}, ["product_id", "reason"])},
    {"name": "illustrate", "description": "Ask the operator to pay for one illustration for a product's cover "
     "(FLUX.2, a few cents): describe the picture, no words in it, no real people, logos or brands. Waits for their "
     "approval; without one the cover is typographic.",
     "input_schema": _schema({"product_id": S, "prompt": S}, ["product_id", "prompt"])},
    {"name": "make_bundle", "description": "Put 2 to 6 existing products (yours or other co-ops') together as one "
     "product, with its own title, description, tags and price: at least $5 and at least its dearest part, up to "
     "$49.99. Bundles are worth far more than singles. Free; it's a draft until you list it (and the operator "
     "approves). Its sales are shared: 15% to you, the rest to the parts' makers by price.",
     "input_schema": _schema({"product_ids": {"type": "array", "items": S}, "title": S, "description": S,
                              "tags": S, "price": N}, ["product_ids", "title", "description", "tags", "price"])},
    {"name": "list_product", "description": "Ask the operator to list one of your draft products on one or more sales "
     "channels (a list of names from your desk view). Its listing is checked against the store's limits and rules "
     "first. Free; nothing goes public until the operator approves.",
     "input_schema": _schema({"product_id": S, "channels": {"type": "array", "items": S}}, ["product_id", "channels"])},
    {"name": "set_price", "description": "Ask the operator to change a listed product's price (USD, 5.00 to 49.99). "
     "Free; waits for their approval.", "input_schema": _schema({"product_id": S, "price": N}, ["product_id", "price"])},
)


def parse_listing(text: str) -> dict:
    """Title, Description, Tags and Price from a listing part (lines or sections starting with each name)."""
    found = {}
    for name in ("Title", "Description", "Tags", "Price"):
        m = re.search(rf"^\W*{name}\W*[:\n]\s*(.+?)(?=^\W*(Title|Description|Tags|Price)\b|\Z)", text, re.I | re.M | re.S)
        found[name.lower()] = m.group(1).strip() if m else ""
    price = re.search(r"\d+(\.\d{1,2})?", found["price"])
    return {"title": found["title"].splitlines()[0][:400] if found["title"] else "", "description": found["description"],
            "tags": tuple(t.strip() for t in found["tags"].split(",") if t.strip()),
            "price": float(price.group(0)) if price else 0.0}


DISCLOSURE = "About this product:"


def disclosed(description: str, art: bool) -> str:
    """The description with an honest note on how it was made, once (your decision, 6 Oct; Etsy expects AI use to be
    disclosed). Every product here is written with AI tools; an illustration is generated with FLUX.2."""
    base = description.split(f"\n\n{DISCLOSURE}")[0].rstrip()
    how = ("written and designed with the help of AI tools" + (", with a cover illustration generated by AI (FLUX.2)"
           if art else "") + ", and reviewed by a person before listing.")
    return f"{base}\n\n{DISCLOSURE} {how}"


def listing_problems(p: Product) -> list[str]:
    out = []
    if not p.title or len(p.title) > MAX_TITLE:
        out.append(f"the title must be 1 to {MAX_TITLE} characters (it is {len(p.title)})")
    if not p.tags or len(p.tags) > MAX_TAGS or any(len(t) > MAX_TAG for t in p.tags):
        out.append(f"1 to {MAX_TAGS} tags, each at most {MAX_TAG} characters")
    if not PRICES[0] * USD <= p.price <= PRICES[1] * USD:
        out.append(f"the price must be between ${PRICES[0]} and ${PRICES[1]}")
    if not p.description:
        out.append("it has no description")
    return out


@dataclass
class StoreDesk:
    channels: Mapping[str, Channel]
    credit_per_dollar: int = USD  # credits (µ) the maker earns per dollar a sale brings in, after fees
    real: bool = False  # real channels: each sale is also booked in USD (buyer -> sales, fee -> ext:fees)
    drop_after: int = 48  # cycles without a sale before a drop request is raised
    images: Any = None  # an illustration service (packs/storefront/images.py), if one is set up
    folder: str | None = None  # where product files go; the society's folder by default
    tools: tuple = TOOLS
    products: dict[str, Product] = field(default_factory=dict)
    made: set[str] = field(default_factory=set)  # jobs already turned into products

    # ── the cycle ──────────────────────────────────────────────
    def open(self, w) -> None:
        for record in list(w.outputs):
            if record["job"] not in self.made and "listing" in record["parts"]:
                self._make(record)
        for name, channel in sorted(self.channels.items()):
            for sale in channel.sales(w.cycle):
                self._book(w, name, sale)

    def close(self, w) -> None:
        """The kill criteria: a request to you, never a drop by itself."""
        for p in self.products.values():
            quiet_since = p.last_sale or p.listed_at
            if p.stage == Stage.LISTED and quiet_since is not None and w.cycle - quiet_since >= self.drop_after:
                why = f"no sale in {w.cycle - quiet_since} cycles on {', '.join(sorted(p.listings))}"
                w.approvals.request(p.maker, "rule", "drop_product", "publish", p.id, self._detail(p, "Drop", why))

    def _make(self, record: dict) -> None:
        self.made.add(record["job"])
        fields = parse_listing(record["parts"]["listing"]["text"])
        scores = list(record["scores"].values())
        pid = f"P{len(self.products) + 1}"
        self.products[pid] = Product(pid, record["job"], record["prime"], fields["title"], fields["description"],
                                     fields["tags"], round(fields["price"] * USD),
                                     sum(scores) / len(scores) if scores else 0.5,
                                     content=record["parts"].get("content", {}).get("text", ""))

    def _book(self, w, channel: str, sale) -> None:
        p = next((x for x in self.products.values() if sale.listing and x.listings.get(channel) == sale.listing), None)
        if p is None:
            return
        net = round((sale.gross - sale.fee) * self.credit_per_dollar / USD)
        if self.real:
            self._book_dollars(w, p, channel, sale)
        if sale.refund:
            for who, share in self._shares(p, max(net, 0)):
                if back := min(share, w.ledger.balance(purse(who))):
                    w.ledger.transfer(purse(who), "market", back, cycle=w.cycle, kind="refund", memo=p.id)
            p.sold, p.revenue = p.sold - 1, p.revenue - sale.gross
            w.tell(p.maker, "refund", f"{p.id} was refunded on {channel}: ${sale.gross / USD:.2f}")
            return
        p.sold, p.revenue, p.last_sale = p.sold + 1, p.revenue + sale.gross, w.cycle
        for who, share in self._shares(p, max(net, 0)):
            if share > 0:
                w.ledger.settle_revenue(who, share, cycle=w.cycle, memo=f"{p.id} on {channel}")
        w.tell(p.maker, "sale", f"{p.id} {p.title!r} sold on {channel} for ${sale.gross / USD:.2f}"
                                f" (fee ${sale.fee / USD:.2f})")

    @staticmethod
    def _book_dollars(w, p: Product, channel: str, sale) -> None:
        """The real money, in USD beside the credits, never mixed with them: what the buyer paid, the channel's fee,
        and what's left, held in `sales` (yours). A refund reverses it, as far as `sales` holds."""
        sign = -1 if sale.refund else 1
        legs = [("ext:sales", -sign * sale.gross), ("ext:fees", sign * sale.fee), ("sales", sign * (sale.gross - sale.fee))]
        if sale.refund and w.ledger.balance("sales", "USD") < sale.gross - sale.fee:
            return  # nothing left to reverse here: the refund came out of money already paid out to you
        w.ledger.post(legs, cycle=w.cycle, kind="refund" if sale.refund else "sale", memo=f"{p.id} on {channel}",
                      currency="USD")

    # ── tools ──────────────────────────────────────────────────
    def call(self, w, coop: str, tool: str, args: dict) -> tuple[bool, str]:
        if tool == "make_bundle":
            return self._bundle(w, coop, args)
        p = self.products.get(str(args.get("product_id", "")))
        if p is None or p.maker != coop:
            return False, f"you have no product {args.get('product_id')!r}; your desk view lists yours"
        if tool == "list_product":
            return self._ask_listing(w, coop, p, args.get("channels") or [])
        if tool == "illustrate":
            return self._ask_art(w, coop, p, " ".join(str(args.get("prompt", "")).split())[:800])
        if p.stage != Stage.LISTED:
            return False, f"{p.id} isn't listed (it is {p.stage})"
        if tool == "set_price":
            try:
                price = round(float(args["price"]) * USD)
            except (KeyError, TypeError, ValueError):
                return False, "give the new price in dollars"
            if not PRICES[0] * USD <= price <= PRICES[1] * USD:
                return False, f"the price must be between ${PRICES[0]} and ${PRICES[1]}"
            p.wanted = {"price": price}
            return self._ask(w, coop, "set_price", p, self._detail(p, "New price", f"${price / USD:.2f}"))
        return self._ask(w, coop, "drop_product", p, self._detail(p, "Drop", str(args.get("reason", ""))[:300]))

    def _ask_listing(self, w, coop: str, p: Product, channels) -> tuple[bool, str]:
        if p.stage not in (Stage.DRAFT, Stage.DROPPED):
            return False, f"{p.id} is {p.stage}"
        if not self.channels:
            return False, "no sales channel is connected to this society yet"
        unknown = [c for c in channels if c not in self.channels]
        if not channels or unknown:
            return False, f"choose channels from: {', '.join(sorted(self.channels))}"
        if problems := listing_problems(p):
            return False, "the listing can't go out as it is: " + "; ".join(problems)
        if why := screen(w, coop, "listing", f"Title: {p.title}\n{p.description}\nTags: {', '.join(p.tags)}"):
            return False, why
        p.wanted = {"channels": sorted(set(channels))}
        p.description = disclosed(p.description, bool(p.art))
        if folder := self._folder(w):
            art = Path(p.art).read_bytes() if p.art and Path(p.art).exists() else None
            p.files = {k: str(v) for k, v in files.write(folder, p.id, p.title, p.content or p.description, art).items()}
        detail = self._detail(p, "List on", ", ".join(p.wanted["channels"]))
        ok, message = self._ask(w, coop, "list_product", p, detail)
        if ok:
            p.stage = Stage.REQUESTED
        return ok, message

    def _bundle(self, w, coop: str, args: dict) -> tuple[bool, str]:
        ids = list(dict.fromkeys(str(i) for i in args.get("product_ids") or []))
        parts = [self.products.get(i) for i in ids]
        if not BUNDLE[0] <= len(ids) <= BUNDLE[1] or any(p is None or p.stage == Stage.DROPPED or p.parts for p in parts):
            return False, f"a bundle is {BUNDLE[0]} to {BUNDLE[1]} existing products (not dropped, not bundles themselves)"
        found = [p for p in parts if p is not None]
        try:
            price = round(float(args["price"]) * USD)
        except (KeyError, TypeError, ValueError):
            return False, "give the bundle's price in dollars"
        if price < max(p.price for p in found):
            return False, f"a bundle can't cost less than its dearest part (${max(p.price for p in found) / USD:.2f})"
        pid = f"P{len(self.products) + 1}"
        bundle = Product(pid, "bundle", coop, str(args.get("title", "")).strip(), str(args.get("description", "")).strip(),
                         tuple(t.strip() for t in str(args.get("tags", "")).split(",") if t.strip()), price,
                         sum(p.quality for p in found) / len(found), parts=tuple(ids),
                         content="\n\n".join(f"{p.title}\n\n{p.content or p.description}" for p in found))
        if problems := listing_problems(bundle):
            return False, "the bundle can't be made as it is: " + "; ".join(problems)
        if why := screen(w, coop, "listing", f"Title: {bundle.title}\n{bundle.description}\nTags: {', '.join(bundle.tags)}"):
            return False, why
        self.products[pid] = bundle
        return True, f"bundle {pid} made from {', '.join(ids)} at ${price / USD:.2f}: a draft; list it with list_product"

    def _shares(self, p: Product, net: int) -> list[tuple[str, int]]:
        """Who a sale pays: the maker; for a bundle, its assembler and its parts' makers, by price."""
        parts = [self.products[i] for i in p.parts if i in self.products]
        if not parts:
            return [(p.maker, net)]
        assembler = round(net * ASSEMBLER)
        total = sum(x.price for x in parts)
        out = [(p.maker, assembler)] + [(x.maker, (net - assembler) * x.price // total) for x in parts]
        out[0] = (p.maker, assembler + net - sum(a for _, a in out))  # what integer division leaves over
        return out

    def _ask_art(self, w, coop: str, p: Product, prompt: str) -> tuple[bool, str]:
        if self.images is None:
            return False, "no illustration service is set up; covers are typographic"
        if len(prompt) < 10:
            return False, "describe the picture"
        if why := screen(w, coop, "listing", prompt):
            return False, why
        p.art_prompt = prompt
        cost = getattr(self.images, "price", 0) / USD
        out = w.approvals.request(coop, "steward", "illustrate", "spend", p.id,
                                  f"Illustrate {p.id} ({p.title}) for about ${cost:.2f}:\n{prompt}")
        return out.ok, out.message

    def _ask(self, w, coop: str, tool: str, p: Product, detail: str) -> tuple[bool, str]:
        out = w.approvals.request(coop, "steward", tool, "publish", p.id, detail)
        return out.ok, out.message

    def _folder(self, w) -> Path | None:
        if self.folder:
            return Path(self.folder)
        ledger = w.params.storage.ledger_path
        return Path(ledger).parent if ledger != ":memory:" else None

    @staticmethod
    def _detail(p: Product, what: str, value: str) -> str:
        where = "".join(f"\n{k}: {v}" for k, v in sorted(p.files.items()))
        return (f"{what}: {value}\nProduct {p.id} by {p.maker} (job {p.job}, graded {p.quality:.2f})\n"
                f"Title: {p.title}\nPrice: ${p.price / USD:.2f}\nTags: {', '.join(p.tags)}\nDescription:\n{p.description}"
                + (f"\nFiles (open them before approving):{where}" if where else ""))

    # ── what you approved ──────────────────────────────────────
    def carry_out(self, w, r) -> tuple[bool, str]:
        """Runs outside the world's lock (channels and images are the network); takes it to change the product."""
        p = self.products.get(r.target)
        if p is None:
            return False, f"no product {r.target}"
        act = {"list_product": self._list, "set_price": self._reprice, "illustrate": self._illustrate}.get(r.tool, self._drop)
        return act(w, p)

    def _list(self, w, p: Product) -> tuple[bool, str]:
        done, kits = {}, []
        for c in p.wanted.get("channels", []):
            channel = self.channels.get(c)
            if channel is None:
                continue
            done[c] = channel.list(p.title, p.description, p.tags, p.price, p.quality, p.files)
            if channel.manual:
                kits.append(c)
        with w.lock:
            p.listings.update(done)
            p.stage, p.listed_at = Stage.LISTED, w.cycle
        note = "".join(f" {c}: create it by hand from {p.files.get('pdf', 'its files')} and the listing above, then "
                       f"run `commons link <society> {p.id} {c} <id>`." for c in kits)
        return True, f"{p.id} listed on {', '.join(sorted(c for c in done if c not in kits)) or 'no channel by API'}." + note

    def _reprice(self, w, p: Product) -> tuple[bool, str]:
        price = p.wanted["price"]
        manual = [c for c, listing in p.listings.items() if self.channels[c].manual]
        for c, listing in p.listings.items():
            self.channels[c].set_price(listing, price)
        with w.lock:
            p.price = price
        return True, f"{p.id} now ${price / USD:.2f}" + (f"; change it by hand on {', '.join(manual)}" if manual else "")

    def _drop(self, w, p: Product) -> tuple[bool, str]:
        manual = [c for c in p.listings if self.channels[c].manual]
        for c, listing in p.listings.items():
            self.channels[c].unlist(listing)
        with w.lock:
            p.listings, p.stage = {}, Stage.DROPPED
        return True, f"{p.id} unlisted" + (f"; archive it by hand on {', '.join(manual)}" if manual else "")

    def _illustrate(self, w, p: Product) -> tuple[bool, str]:
        folder = self._folder(w)
        if self.images is None or folder is None:
            return False, "no illustration service or folder"
        art = self.images.generate(p.art_prompt)
        path = folder / "products" / p.id / "art.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(art)
        with w.lock:
            p.art = str(path)
            w.meter.record_bill(p.maker, "illustration", getattr(self.images, "price", 0), cycle=w.cycle)
        return True, f"{p.id} has an illustration ({path}); it goes on the cover when you list it"

    def link(self, product_id: str, channel: str, listing: str) -> str:
        """A product you listed by hand on a manual channel, linked so its sales are collected."""
        p = self.products.get(product_id)
        if p is None or channel not in p.listings:
            raise ValueError(f"{product_id} has no listing on {channel} waiting for a link")
        p.listings[channel] = listing
        if link := getattr(self.channels[channel], "link", None):
            link(listing)
        return f"{product_id} linked to {channel} {listing}"

    # ── what a co-op sees ──────────────────────────────────────
    def view(self, w, coop: str) -> str:
        mine = [p for p in self.products.values() if p.maker == coop]
        lines = [f"Channels connected: {', '.join(sorted(self.channels)) or 'none yet'}. Listing, prices and drops wait "
                 "for the operator's approval."]
        for p in mine[-12:]:
            where = f" on {', '.join(sorted(p.listings))}" if p.listings else ""
            lines.append(f"  {p.id} [{p.stage}{where}] {p.title!r} ${p.price / USD:.2f} · sold {p.sold} "
                         f"(${p.revenue / USD:.2f})" + (f" · last sale cycle {p.last_sale}" if p.last_sale else ""))
        if not mine:
            lines.append("  You have no products yet: a product job you finish becomes one.")
        return "\n".join(lines)
