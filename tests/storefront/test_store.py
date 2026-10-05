"""P2.3, P2.4, P2.6: the store. Listing, repricing and dropping go through the gate as publish requests carrying
everything that would go public; nothing reaches a channel until you approve. A product can be on several channels
(combinations). Sales pay the maker after the channel's fee. A product that stops selling raises a drop request; you
still decide."""

from commons.application.actions import Actions
from commons.application.society import Params, World
from commons.domain.gate import GatePolicy
from commons.domain.pack import load
from commons.domain.status import RequestStatus
from commons.substrate.ledger import purse
from packs.storefront.channels import USD, FakeChannel
from packs.storefront.desk import Product, Stage, StoreDesk


def store(publish="ask", channels=None, drop_after=48):
    pack = load("storefront")
    channels = {"etsy": FakeChannel("etsy", base_rate=0.9), "lemonsqueezy": FakeChannel("lemonsqueezy", base_rate=0.9)} \
        if channels is None else channels
    w = World(Params(**{**pack.params, "seed": 0, "verify": False, "jobs_per_cycle": 0}), pack=pack,
              desk=StoreDesk(channels, credit_per_dollar=16_000, drop_after=drop_after))
    w.gate.policy = GatePolicy(publish=publish)
    w.step()
    w.desk.products["P1"] = Product("P1", "J1", "scribes", "30-Day KJV Bible Reading Plan | Printable PDF",
                                    "Thirty short daily readings, KJV references. 3 pages. A digital download.",
                                    ("bible plan", "kjv", "printable"), round(4.99 * USD), 0.9)
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
    assert r.risk == "publish" and "Title: 30-Day KJV" in r.detail and "$4.99" in r.detail and "etsy, lemonsqueezy" in r.detail
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
    w.desk.products["P1"].price = 49 * USD
    assert "price" in desk(w, "list_product", channels=["etsy"]).message
    assert "choose channels" in desk(w, "list_product", channels=["amazon"]).message


def test_publishing_needs_your_policy_and_a_live_store_has_no_channel_yet():
    assert "doesn't allow publish" in desk(store(publish="deny"), "list_product", channels=["etsy"]).message
    assert "no sales channel" in desk(store(channels={}), "list_product", channels=["etsy"]).message
    assert load("storefront").live_desk(0).channels == {}


def test_a_product_that_stops_selling_raises_a_drop_request_and_only_you_drop_it():
    w = store(channels={"etsy": FakeChannel("etsy", base_rate=0.0)}, drop_after=3)
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.run(5)
    p = w.desk.products["P1"]
    drop = [r for r in w.gate.pending() if r.tool == "drop_product"]
    assert p.stage == Stage.LISTED and len(drop) == 1 and drop[0].actor == "rule" and "no sale in" in drop[0].detail
    approve_all(w)
    w.step()
    assert p.stage == Stage.DROPPED and p.listings == {}


def test_a_price_change_goes_through_the_gate_too():
    w = store()
    desk(w, "list_product", channels=["etsy"])
    approve_all(w)
    w.step()
    assert desk(w, "set_price", price=6.5)
    assert w.desk.products["P1"].price == round(4.99 * USD)  # not until you approve
    approve_all(w)
    w.step()
    assert w.desk.products["P1"].price == round(6.5 * USD)


def test_only_the_maker_can_ask_for_its_product():
    w = store()
    out = Actions(w, w.communities["press"]).desk_call("list_product", {"product_id": "P1", "channels": ["etsy"]})
    assert not out and "no product" in out.message
