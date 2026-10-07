"""The store: products made by the society, listed on channels only with your approval, and their sales.

    a product        every paid product job becomes a draft product: its listing part gives the title,
                     description, tags and price; the maker is the job's prime
    list_product     the maker asks to list it on one or more channels (combinations); the listing is checked
                     (Etsy's limits, the price range, the storefront's rules) and goes to the gate as a publish
                     request carrying everything that would go public. Nothing is listed until you approve
    set_price        a new price, through the gate the same way
    drop_product     unlisting, through the gate the same way (your decision, 5 Oct: dropping needs you)
    kill criteria    your decisions (7 Oct), each only a request to you, never a drop or a pause by itself:
                     a listed product raises a drop request when it has had no sale for 60 days, when at least 3 of
                     its sales and more than 20% were refunded, when a channel took it down, or when it no longer
                     passes the store's rules (re-checked daily, so a tightened rule reaches what's already listed).
                     After you deny one, the rules wait 30 days before asking again. The store raises a pause
                     request when nothing has sold for 90 days, or when its real spend (models, illustrations,
                     listing fees) beat its real sales after fees by more than $25 over the last 30 days
    sales            collected from every channel each cycle and paid to the maker, after the channel's fee, by the
                     ledger's revenue rule; `credit_per_dollar` scales dollars to the society's money (1:1 in a
                     live society; scaled down for simulated credits)

Days are calendar days: the wall clock in a live society, `cycle_seconds` a cycle in a simulated one.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from commons.application.screening import screen
from commons.domain.status import RequestStatus
from commons.domain.pack import screened
from commons.substrate.ledger import purse
from packs.storefront import files
from packs.storefront.channels import USD, Channel

MAX_TITLE, MAX_TAGS, MAX_TAG = 140, 13, 20
PRICES = (5.00, 49.99)  # your floor (6 Oct): $5, so channel fees stay small; aim well above with bundles and packs
DAY = 86_400
# the kill criteria (your decisions, 7 Oct): requests to you, never a drop or a pause by themselves
QUIET_DAYS = 60  # a listed product with no sale this long
REFUNDS = (3, 0.20)  # at least this many refunds, and more than this share of its sales
SNOOZE_DAYS = 30  # after you deny a request, the rules wait this long before asking again
STORE_QUIET_DAYS = 90  # nothing in the store sold: a pause request
LOSS_DAYS, LOSS_LIMIT = 30, 25 * USD  # real spend over real sales (after fees) in this window: a pause request


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
    listed_t: float | None = None  # the same, as calendar time (seconds), for the kill criteria
    sold_t: float | None = None
    sold: int = 0
    refunds: int = 0
    revenue: int = 0  # µ$ gross
    content: str = ""  # the product itself (its content part), for the PDF
    files: dict = field(default_factory=dict)  # pdf, cover: paths, written when a listing is requested
    art: str = ""  # an approved illustration (a path), for the cover
    art_prompt: str = ""  # what an illustration request asked for
    parts: tuple[str, ...] = ()  # a bundle: the products it's made of
    flags: dict[str, str] = field(default_factory=dict)  # the daily check: channels that took it down, the rules
    checked_t: float = 0.0
    drop_ask: str = ""  # the drop request the rules raised, while it waits for you
    snoozed_until: float = 0.0  # you denied one: no new request before this


def _schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {**props, "why": {"type": "string", "description": "optional: why"}},
            "required": required, "additionalProperties": False}


S, N = {"type": "string"}, {"type": "number"}
BUNDLE = (2, 6)  # products in a bundle
ASSEMBLER = 0.15  # of a bundle's sales, to the co-op that put it together; the rest to its parts' makers, by price

TOOLS = (
    {"name": "drop_product", "description": "Ask the operator to unlist one of your products everywhere. Free; waits "
     "for their approval.", "input_schema": _schema({"product_id": S, "reason": S}, ["product_id", "reason"])},
    {"name": "illustrate", "description": "Ask the operator for one illustration for a product's cover (FLUX.2; "
     "free on this machine, a few cents by API): describe the picture, no words in it, no real people, logos or brands. Waits for their "
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
    quiet_days: float = QUIET_DAYS
    cycle_seconds: float = DAY  # the calendar time a cycle stands for; 0: the wall clock (a live society)
    images: Any = None  # an illustration service (packs/storefront/images.py), if one is set up
    folder: str | None = None  # where product files go; the society's folder by default
    tools: tuple = TOOLS
    products: dict[str, Product] = field(default_factory=dict)
    made: set[str] = field(default_factory=set)  # jobs already turned into products
    first_listed_t: float | None = None
    store_sold_t: float | None = None
    net_usd: int = 0  # µ$ real sales after the channels' fees, refunds taken off
    days: list[tuple[float, int, int]] = field(default_factory=list)  # (when, real spend, net_usd), one a day
    store_ask: str = ""
    store_snoozed_until: float = 0.0

    def now(self, cycle: int) -> float:
        return cycle * self.cycle_seconds if self.cycle_seconds else time.time()

    # ── the cycle ──────────────────────────────────────────────
    def open(self, w) -> None:
        for record in list(w.outputs):
            if record["job"] not in self.made and "listing" in record["parts"]:
                self._make(record)
        for name, channel in sorted(self.channels.items()):
            for sale in channel.sales(w.cycle):
                self._book(w, name, sale)
        now = self.now(w.cycle)
        for p in self.products.values():
            if p.stage == Stage.LISTED and now - p.checked_t >= DAY:
                self._check(w, p, now)

    def close(self, w) -> None:
        """The kill criteria: requests to you, never a drop or a pause by themselves."""
        now = self.now(w.cycle)
        for p in self.products.values():
            if p.stage != Stage.LISTED:
                continue
            p.drop_ask, p.snoozed_until = self._answered(w, p.drop_ask, now, p.snoozed_until)
            if p.drop_ask or now < p.snoozed_until or not (reasons := self._drop_reasons(p, now)):
                continue
            numbers = (f"listed {(now - (p.listed_t or now)) / DAY:.0f} days; sold {p.sold}, refunded {p.refunds}, "
                       f"${p.revenue / USD:.2f} gross")
            out = w.approvals.request(p.maker, "rule", "drop_product", "publish", p.id,
                                      self._detail(p, "Drop", "; ".join(reasons) + f" ({numbers})"))
            p.drop_ask = out.id or ""
        self._review_store(w, now)

    def _check(self, w, p: Product, now: float) -> None:
        """Once a day: has a channel taken it down, and does it still pass the store's rules (which may have changed)?"""
        p.checked_t, p.flags = now, {}
        for c, listing in sorted(p.listings.items()):
            if listing and (why := self.channels[c].taken_down(listing)):
                p.flags[c] = f"{c} took it down ({why})"
        if why := screened(w.pack, "listing", f"Title: {p.title}\n{p.description}\nTags: {', '.join(p.tags)}"):
            p.flags["rules"] = f"it no longer passes the store's rules: {why}"

    def _drop_reasons(self, p: Product, now: float) -> list[str]:
        out = []
        since = max(p.listed_t or 0.0, p.sold_t or 0.0)
        if p.listed_t is not None and now - since >= self.quiet_days * DAY:
            out.append(f"no sale in {(now - since) / DAY:.0f} days on {', '.join(sorted(p.listings))}")
        made = p.sold + p.refunds  # `sold` already has the refunds taken off
        if p.refunds >= REFUNDS[0] and p.refunds > REFUNDS[1] * made:
            out.append(f"{p.refunds} of its {made} sales refunded ({p.refunds / made:.0%})")
        return out + [p.flags[k] for k in sorted(p.flags)]

    @staticmethod
    def _answered(w, ask: str, now: float, snoozed: float) -> tuple[str, float]:
        """A request the rules raised: still waiting (kept), denied (no new one for SNOOZE_DAYS), or anything else
        (expired unanswered, approved, failed): cleared, so the rules may ask again."""
        r = w.gate.requests.get(ask) if ask else None
        if r is None:
            return "", snoozed
        if r.status == RequestStatus.PENDING:
            return ask, snoozed
        return "", (now + SNOOZE_DAYS * DAY if r.status == RequestStatus.DENIED else snoozed)

    def _review_store(self, w, now: float) -> None:
        """The store as a whole: a pause request (the gate's govern class) when it has stopped selling or is losing
        real money. Only once something has been listed."""
        if self.first_listed_t is None:
            return
        spend = w.ledger.balance("ext:anthropic", "USD") + w.ledger.balance("ext:services", "USD") if self.real else 0
        if not self.days or now - self.days[-1][0] >= DAY:
            self.days.append((now, spend, self.net_usd))
            self.days = [d for d in self.days if now - d[0] <= (LOSS_DAYS + 1) * DAY]
        self.store_ask, self.store_snoozed_until = self._answered(w, self.store_ask, now, self.store_snoozed_until)
        if self.store_ask or now < self.store_snoozed_until:
            return
        reasons = []
        since = self.store_sold_t or self.first_listed_t
        if now - since >= STORE_QUIET_DAYS * DAY:
            reasons.append(f"nothing in the store has sold for {(now - since) / DAY:.0f} days")
        base = next((d for d in reversed(self.days) if now - d[0] >= LOSS_DAYS * DAY), self.days[0])
        spent, earned = spend - base[1], self.net_usd - base[2]
        if self.real and spent - earned > LOSS_LIMIT:
            reasons.append(f"in the last {min(LOSS_DAYS, round((now - base[0]) / DAY))} days it spent "
                           f"${spent / USD:.2f} of real money and took ${earned / USD:.2f} after fees, "
                           f"${(spent - earned) / USD:.2f} down (the limit is ${LOSS_LIMIT / USD:.0f})")
        if reasons:
            listed = [p for p in self.products.values() if p.stage == Stage.LISTED]
            detail = (f"Pause the society: {'; '.join(reasons)}\nListed: {len(listed)} products; sold "
                      f"{sum(p.sold for p in self.products.values())} in all. Ticks skip a paused society until "
                      "`commons resume NAME`.")
            makers = sorted(p.maker for p in (listed or self.products.values()) if p.maker in w.communities)
            if makers:  # filed in the name of the co-op with the most listings, so its members hear of it too
                who = max(sorted(set(makers)), key=makers.count)
                self.store_ask = w.approvals.request(who, "rule", "pause_society", "govern", "society", detail).id or ""

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
            p.sold, p.revenue, p.refunds = p.sold - 1, p.revenue - sale.gross, p.refunds + 1
            w.tell(p.maker, "refund", f"{p.id} was refunded on {channel}: ${sale.gross / USD:.2f}")
            return
        p.sold, p.revenue, p.last_sale = p.sold + 1, p.revenue + sale.gross, w.cycle
        p.sold_t = self.store_sold_t = self.now(w.cycle)
        for who, share in self._shares(p, max(net, 0)):
            if share > 0:
                w.ledger.settle_revenue(who, share, cycle=w.cycle, memo=f"{p.id} on {channel}")
        w.tell(p.maker, "sale", f"{p.id} {p.title!r} sold on {channel} for ${sale.gross / USD:.2f}"
                                f" (fee ${sale.fee / USD:.2f})")

    def _book_dollars(self, w, p: Product, channel: str, sale) -> None:
        """The real money, in USD beside the credits, never mixed with them: what the buyer paid, the channel's fee,
        and what's left, held in `sales` (yours). A refund reverses it, as far as `sales` holds."""
        sign = -1 if sale.refund else 1
        legs = [("ext:sales", -sign * sale.gross), ("ext:fees", sign * sale.fee), ("sales", sign * (sale.gross - sale.fee))]
        if sale.refund and w.ledger.balance("sales", "USD") < sale.gross - sale.fee:
            return  # nothing left to reverse here: the refund came out of money already paid out to you
        w.ledger.post(legs, cycle=w.cycle, kind="refund" if sale.refund else "sale", memo=f"{p.id} on {channel}",
                      currency="USD")
        self.net_usd += sign * (sale.gross - sale.fee)

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
        how = f"for about ${cost:.2f}" if cost else "on this machine (no charge)"
        out = w.approvals.request(coop, "steward", "illustrate", "spend", p.id,
                                  f"Illustrate {p.id} ({p.title}) {how}:\n{prompt}")
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
        if r.tool == "pause_society":
            return self._pause(w, r)
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
            p.listed_t = p.checked_t = self.now(w.cycle)
            self.first_listed_t = self.first_listed_t or p.listed_t
            if self.real:
                for c in done:
                    if fee := self.channels[c].listing_fee:
                        w.meter.record_bill(p.maker, f"listing {p.id} on {c}", fee, cycle=w.cycle)
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
            p.listings, p.stage, p.flags, p.drop_ask = {}, Stage.DROPPED, {}, ""
        return True, f"{p.id} unlisted" + (f"; archive it by hand on {', '.join(manual)}" if manual else "")

    def _pause(self, w, r) -> tuple[bool, str]:
        """A society on the schedule (a registry folder) gets the `paused` file `commons pause` writes; a one-off run
        is halted."""
        ledger = Path(w.params.storage.ledger_path)
        folder = ledger.parent.parent if ledger.parent.name == "state" else ledger.parent
        if ledger.name != ":memory:" and ((folder / "state").is_dir() or (folder / "society.toml").exists()):
            (folder / "paused").write_text(f"paused {time.strftime('%Y-%m-%d %H:%M')} by the store's rules ({r.id})\n")
            return True, f"paused: ticks skip it until `commons resume {folder.name}`"
        with w.lock:
            w.meter.halt(f"paused by the store's rules ({r.id})", w.cycle)
        return True, "the run is halted"

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
            if price := getattr(self.images, "price", 0):
                w.meter.record_bill(p.maker, "illustration", price, cycle=w.cycle)
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
