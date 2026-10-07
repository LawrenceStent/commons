"""P2.3, P2.4, P2.6: the store. Listing, repricing and dropping go through the gate as publish requests carrying
everything that would go public; nothing reaches a channel until you approve. A product can be on several channels
(combinations). Sales pay the maker after the channel's fee. The kill criteria (7 Oct) raise drop and pause requests;
you still decide, and a denial holds them off for 30 days."""

from commons.application.actions import Actions
from commons.application.society import Params, World
from commons.domain.gate import GatePolicy
from commons.domain.pack import load
from commons.domain.status import RequestStatus
from commons.substrate.ledger import purse
from packs.storefront.channels import USD, FakeChannel
from packs.storefront.desk import Product, Stage, StoreDesk


def store(publish="ask", channels=None, quiet_days=60, real=False):
    pack = load("storefront")
    channels = {"etsy": FakeChannel("etsy", base_rate=0.9), "lemonsqueezy": FakeChannel("lemonsqueezy", base_rate=0.9)} \
        if channels is None else channels
    w = World(Params(**{**pack.params, "seed": 0, "verify": False, "jobs_per_cycle": 0}), pack=pack,
              desk=StoreDesk(channels, credit_per_dollar=16_000, quiet_days=quiet_days, real=real))  # a cycle is a day
    w.gate.policy = GatePolicy(publish=publish)
    w.step()
    w.desk.products["P1"] = Product("P1", "J1", "scribes", "30-Day KJV Bible Reading Plan | Printable PDF",
                                    "Thirty short daily readings, KJV references. 3 pages. A digital download.",
                                    ("bible plan", "kjv", "printable"), round(7.99 * USD), 0.9)
    return w


def desk(w, tool, **args):
    return Actions(w, w.communities["scribes"]).desk_call(tool, {"product_id": "P1", **args})


def approve_all(w):
    w.web_desk.decide([r.id for r in w.gate.pending()], True)


def test_a_listing_waits_for_you_then_goes_on_every_channel_chosen_and_sells():
    w = store()
    out = desk(w, "list_product", channels=["etsy", "lemonsqueezy"])
    assert out and "waiting for the operator's approval" in out.message
    r = w.gate.pending()[0]
    assert r.risk == "publish" and "Title: 30-Day KJV" in r.detail and "$7.99" in r.detail and "etsy, lemonsqueezy" in r.detail
    w.step()
    assert w.desk.products["P1"].listings == {}  # nothing public before you decide
    approve_all(w)
    before = w.ledger.balance(purse("scribes"))
    w.run(3)
    p = w.desk.products["P1"]
    assert p.stage == Stage.LISTED and set(p.listings) == {"etsy", "lemonsqueezy"}
    assert p.sold > 0 and w.ledger.balance(purse("scribes")) > before
    assert r.status == RequestStatus.DONE
    w.ledger.check()


def test_a_listing_that_breaks_a_rule_or_its_limits_never_reaches_the_gate():
    w = store()
    w.desk.products["P1"].description += " Only 3 left, hurry!"
    out = desk(w, "list_product", channels=["etsy"])
    assert not out and "pressure" in out.message and w.gate.requests == {}
    w.desk.products["P1"].description = "A plan."
    w.desk.products["P1"].price = 99 * USD
    assert "price" in desk(w, "list_product", channels=["etsy"]).message
    assert "choose channels" in desk(w, "list_product", channels=["amazon"]).message


def test_publishing_needs_your_policy_and_a_live_store_has_no_channel_yet():
    assert "doesn't allow publish" in desk(store(publish="deny"), "list_product", channels=["etsy"]).message
    assert "no sales channel" in desk(store(channels={}), "list_product", channels=["etsy"]).message
    assert load("storefront").live_desk(0).channels == {}


def drops(w):
    return [r for r in w.gate.pending() if r.tool == "drop_product"]


def test_a_product_that_stops_selling_raises_a_drop_request_and_only_you_drop_it():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)}, quiet_days=3)
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(5)
    p = w.desk.products["P1"]
    assert p.stage == Stage.LISTED and len(drops(w)) == 1 and drops(w)[0].actor == "rule"
    assert "no sale in 3 days" in drops(w)[0].detail and "sold 0" in drops(w)[0].detail
    approve_all(w)
    w.step()
    assert p.stage == Stage.DROPPED and p.listings == {}


def test_the_quiet_period_is_sixty_calendar_days_not_cycles():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)})
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(59)
    assert drops(w) == []
    w.run(2)
    assert len(drops(w)) == 1 and "no sale in 60 days" in drops(w)[0].detail
    hourly = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)})
    hourly.desk.cycle_seconds = 3600  # a society ticking hourly: 61 cycles is under 3 days
    desk(hourly, "list_product", channels=["etsy"])
    approve_all(hourly)
    hourly.run(61)
    assert drops(hourly) == []


def test_after_you_deny_a_drop_the_rules_wait_thirty_days_before_asking_again():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)}, quiet_days=3)
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(5)
    w.web_desk.decide([drops(w)[0].id], False, reason="give it the summer")
    w.run(29)
    assert drops(w) == []
    w.run(3)
    assert len(drops(w)) == 1 and w.desk.products["P1"].stage == Stage.LISTED


def test_frequent_refunds_raise_a_drop_request():
    from packs.storefront.channels import Sale
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)})
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.step()
    p, listing = w.desk.products["P1"], w.desk.products["P1"].listings["etsy"]
    for refund in (False,) * 10 + (True,) * 2:
        w.desk._book(w, "etsy", Sale(listing, p.price, USD, w.cycle, refund=refund))
    w.step()
    assert drops(w) == []  # 2 of 10: not yet
    w.desk._book(w, "etsy", Sale(listing, p.price, USD, w.cycle, refund=True))
    w.step()
    assert len(drops(w)) == 1 and "3 of its 10 sales refunded (30%)" in drops(w)[0].detail


def test_a_channel_takedown_or_a_rule_it_now_breaks_raises_a_drop_request():
    etsy = FakeChannel("etsy", base_rate=0.0)
    w = store(channels={"etsy": etsy})
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(2)
    assert drops(w) == []
    etsy.down.add(w.desk.products["P1"].listings["etsy"])
    w.run(2)
    assert len(drops(w)) == 1 and "etsy took it down" in drops(w)[0].detail
    w2 = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)})
    desk(w2, "list_product", channels=["etsy"])
    approve_all(w2)
    w2.step()
    w2.desk.products["P1"].description += " Official merchandise."  # as if a rule had tightened since it was listed
    w2.run(2)
    assert len(drops(w2)) == 1 and "no longer passes the store's rules" in drops(w2)[0].detail


def test_a_store_that_stops_selling_raises_one_pause_request():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)}, quiet_days=1000)
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(89)
    assert not [r for r in w.gate.pending() if r.tool == "pause_society"]
    w.run(3)
    pauses = [r for r in w.gate.pending() if r.tool == "pause_society"]
    assert len(pauses) == 1 and pauses[0].risk == "govern" and "nothing in the store has sold for 90 days" in pauses[0].detail
    approve_all(w)
    w.step()
    assert w.meter.halted  # an in-memory run has no folder to pause, so it halts


def test_a_store_losing_real_money_raises_a_pause_request():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)}, quiet_days=1000, real=True)
    w.meter.real_ceiling = 1000 * USD
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.step()
    w.meter.record_bill("scribes", "illustration", 20 * USD, cycle=w.cycle)
    w.step()
    assert not [r for r in w.gate.pending() if r.tool == "pause_society"]  # $20 down: under the limit
    w.meter.record_bill("scribes", "illustration", 6 * USD, cycle=w.cycle)
    w.step()
    pauses = [r for r in w.gate.pending() if r.tool == "pause_society"]
    assert len(pauses) == 1 and "$26.00 down" in pauses[0].detail


def test_a_price_change_goes_through_the_gate_too():
    w = store()
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.step()
    assert desk(w, "set_price", price=12.5)
    assert w.desk.products["P1"].price == round(7.99 * USD)  # not until you approve
    approve_all(w)
    w.step()
    assert w.desk.products["P1"].price == round(12.5 * USD)


def test_only_the_maker_can_ask_for_its_product():
    w = store()
    out = Actions(w, w.communities["press"]).desk_call("list_product", {"product_id": "P1", "channels": ["etsy"]})
    assert not out and "no product" in out.message


def test_an_approved_illustration_is_billed_in_real_dollars_and_goes_on_the_cover(tmp_path):
    from packs.storefront.images import FluxImages

    w = store()
    assert "spend is \"deny\"" in _illustrate_with(w, FluxImages("k", price=30_000)).message  # your policy decides
    w.gate.policy = GatePolicy(publish="ask", spend="ask")
    w.desk.folder = str(tmp_path)
    w.desk.images = FluxImages("k", price=30_000, transport=lambda *a: (200, b""))
    w.desk.images.generate = lambda prompt: _png()
    assert "logo" not in desk(w, "illustrate", prompt="a quiet wheat field at dawn, soft light").message
    assert w.desk.products["P1"].art == ""  # not before you approve the spend
    request = w.gate.pending()[0]
    assert request.risk == "spend" and "$0.03" in request.detail
    approve_all(w)
    w.step()
    p = w.desk.products["P1"]
    assert p.art.endswith("art.png") and w.ledger.real()["services_spend"] == 30_000
    desk(w, "list_product", channels=["etsy"])
    assert (tmp_path / "products" / "P1" / "cover.png").exists() and "Files (open them before approving)" in \
        w.gate.pending()[0].detail


def test_a_manual_channel_gets_a_kit_then_a_link(tmp_path):
    w = store(channels={"lemonsqueezy": FakeChannel("lemonsqueezy", manual=True, base_rate=0.0)})
    w.desk.folder = str(tmp_path)
    desk(w, "list_product", channels=["lemonsqueezy"])
    approve_all(w)
    w.step()
    p = w.desk.products["P1"]
    request = next(r for r in w.gate.requests.values() if r.tool == "list_product")
    assert p.listings == {"lemonsqueezy": ""} and "commons link" in request.result
    w.desk.link("P1", "lemonsqueezy", "variant-9")
    assert p.listings == {"lemonsqueezy": "variant-9"}


def _png():
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 180, 120)).save(out, "PNG")
    return out.getvalue()


def _illustrate_with(w, images):
    w.desk.images = images
    return desk(w, "illustrate", prompt="a quiet wheat field at dawn, soft light")


def test_every_listing_discloses_ai_use_once_and_names_flux_for_an_illustration():
    from packs.storefront.desk import disclosed

    w = store()
    desk(w, "list_product", channels=["etsy"])
    detail = w.gate.pending()[0].detail
    assert "About this product: written and designed with the help of AI tools, and reviewed by a person" in detail
    again = disclosed(disclosed("A plan.", art=False), art=True)
    assert again.count("About this product:") == 1 and "FLUX.2" in again and again.startswith("A plan.")


def add(w, pid, maker, price):
    w.desk.products[pid] = Product(pid, "J" + pid, maker, f"Product {pid}", f"About {pid}.", ("faith",),
                                   round(price * USD), 0.8, content=f"Content of {pid}.")


def test_a_bundle_of_other_co_ops_products_shares_its_sales_by_price():
    w = store()
    add(w, "P2", "press", 10)
    act = Actions(w, w.communities["scribes"])
    make = lambda **kw: act.desk_call("make_bundle", {"product_ids": ["P1", "P2"], "title": "Faith Starter Bundle",
                                                       "description": "Two printables together.",
                                                       "tags": "bundle, faith", **kw})
    assert "dearest part" in make(price=6).message
    assert "2 to 6" in act.desk_call("make_bundle", {"product_ids": ["P1"], "title": "x", "description": "y",
                                                     "tags": "z", "price": 20}).message
    out = make(price=15)
    assert out and "draft" in out.message
    bundle = w.desk.products["P3"]
    assert bundle.parts == ("P1", "P2") and "Product P2" in bundle.content
    shares: dict[str, int] = {}
    for who, amount in w.desk._shares(bundle, 1_000_000):
        shares[who] = shares.get(who, 0) + amount
    assert sum(shares.values()) == 1_000_000 and shares["scribes"] > shares["press"] > 0  # scribes: assembler + P1


def test_a_listed_bundle_pays_its_parts_makers_when_it_sells():
    w = store()
    add(w, "P2", "press", 10)
    Actions(w, w.communities["scribes"]).desk_call("make_bundle", {
        "product_ids": ["P1", "P2"], "title": "Faith Starter Bundle", "description": "Two printables together.",
        "tags": "bundle, faith", "price": 15})
    Actions(w, w.communities["scribes"]).desk_call("list_product", {"product_id": "P3", "channels": ["etsy"]})
    approve_all(w)
    before = w.ledger.balance(purse("press"))
    w.run(4)
    assert w.desk.products["P3"].sold > 0 and w.ledger.balance(purse("press")) > before
