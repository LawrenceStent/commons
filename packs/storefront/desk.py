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

from commons.application.screening import screen
from packs.storefront.channels import USD, Channel

MAX_TITLE, MAX_TAGS, MAX_TAG = 140, 13, 20
PRICES = (1.99, 19.99)


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


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "why": {"type": "string", "description": "optional: why"}},
            "required": required, "additionalProperties": False}


S, N = {"type": "string"}, {"type": "number"}
TOOLS = (
    {"name": "drop_product", "description": "Ask the operator to unlist one of your products everywhere. Free; waits "
     "for their approval.", "input_schema": _schema({"product_id": S, "reason": S}, ["product_id", "reason"])},
    {"name": "list_product", "description": "Ask the operator to list one of your draft products on one or more sales "
     "channels (a list of names from your desk view). Its listing is checked against the store's limits and rules "
     "first. Free; nothing goes public until the operator approves.",
     "input_schema": _schema({"product_id": S, "channels": {"type": "array", "items": S}}, ["product_id", "channels"])},
    {"name": "set_price", "description": "Ask the operator to change a listed product's price (USD, 1.99 to 19.99). "
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
    credit_per_dollar: int = USD  # the society's µ-units per dollar of sales
    drop_after: int = 48  # cycles without a sale before a drop request is raised
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
                                     sum(scores) / len(scores) if scores else 0.5)

    def _book(self, w, channel: str, sale) -> None:
        p = next((x for x in self.products.values() if x.listings.get(channel) == sale.listing), None)
        if p is None:
            return
        p.sold, p.revenue, p.last_sale = p.sold + 1, p.revenue + sale.gross, w.cycle
        net = round((sale.gross - sale.fee) * self.credit_per_dollar / USD)
        if net > 0:
            w.ledger.settle_revenue(p.maker, net, cycle=w.cycle, memo=f"{p.id} on {channel}")
        w.tell(p.maker, "sale", f"{p.id} {p.title!r} sold on {channel} for ${sale.gross / USD:.2f}"
                                f" (fee ${sale.fee / USD:.2f})")

    # ── tools ──────────────────────────────────────────────────
    def call(self, w, coop: str, tool: str, args: dict) -> tuple[bool, str]:
        p = self.products.get(str(args.get("product_id", "")))
        if p is None or p.maker != coop:
            return False, f"you have no product {args.get('product_id')!r}; your desk view lists yours"
        if tool == "list_product":
            return self._ask_listing(w, coop, p, args.get("channels") or [])
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
        detail = self._detail(p, "List on", ", ".join(p.wanted["channels"]))
        ok, message = self._ask(w, coop, "list_product", p, detail)
        if ok:
            p.stage = Stage.REQUESTED
        return ok, message

    def _ask(self, w, coop: str, tool: str, p: Product, detail: str) -> tuple[bool, str]:
        out = w.approvals.request(coop, "steward", tool, "publish", p.id, detail)
        return out.ok, out.message

    @staticmethod
    def _detail(p: Product, what: str, value: str) -> str:
        return (f"{what}: {value}\nProduct {p.id} by {p.maker} (job {p.job}, graded {p.quality:.2f})\n"
                f"Title: {p.title}\nPrice: ${p.price / USD:.2f}\nTags: {', '.join(p.tags)}\nDescription:\n{p.description}")

    # ── what you approved ──────────────────────────────────────
    def carry_out(self, w, r) -> tuple[bool, str]:
        """Runs outside the world's lock (a channel is the network); takes it to change the product."""
        p = self.products.get(r.target)
        if p is None:
            return False, f"no product {r.target}"
        if r.tool == "list_product":
            done = {c: self.channels[c].list(p.title, p.description, p.tags, p.price, p.quality)
                    for c in p.wanted.get("channels", []) if c in self.channels}
            with w.lock:
                p.listings.update(done)
                p.stage, p.listed_at = Stage.LISTED, w.cycle
            return True, f"{p.id} listed on {', '.join(sorted(done))}"
        if r.tool == "set_price":
            for c, listing in p.listings.items():
                self.channels[c].set_price(listing, p.wanted["price"])
            with w.lock:
                p.price = p.wanted["price"]
            return True, f"{p.id} now ${p.price / USD:.2f}"
        for c, listing in p.listings.items():
            self.channels[c].unlist(listing)
        with w.lock:
            p.listings, p.stage = {}, Stage.DROPPED
        return True, f"{p.id} unlisted everywhere"

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
