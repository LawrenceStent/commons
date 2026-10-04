"""K6/T5-T6: the trading pack on the kernel. The broker's limits hold whatever a desk tries, pay follows risk-adjusted
excess return (nothing for trailing the benchmark), model-backed desks trade through the same tools, and the pack's
words stay out of the kernel."""

from dataclasses import replace

from commons.adapters.models import FakeBackend
from commons.agents.llm.fakes import GOOD_GRADE, competent
from commons.agents.llm.steward import LLMStrategy
from commons.application.society import Params, World
from commons.domain.community import Community
from commons.domain.pack import load
from commons.substrate.ledger import purse
from packs.trading.desk import TradingDesk
from packs.trading.prices import FakeMarket
from packs.trading.scripted import Holder, Reckless, Sitter


def society(population, drift=0.0, cycles=48, seed=0):
    pack = load("trading")
    desk = TradingDesk(FakeMarket(seed=seed, drift=drift))
    return World(Params(**{**pack.params, "seed": seed, "verify": False}), pack=pack, population=population,
                 desk=desk).run(cycles)


def refusals(w, coop):
    return {e.text for e in w.activity.recent(5000) if e.community == coop and e.kind == "action" and not e.ok}


def test_every_forbidden_order_is_refused_by_rule():
    w = society([Community("reckless", 2, {"execution"}, Reckless())])
    said = " | ".join(refusals(w, "reckless"))
    for why in ("needs a stop", "more than 20%", "no leverage"):
        assert why in said, why
    account = w.desk.accounts["reckless"]
    assert all(p.stop > 0 for p in account.positions.values())


def test_pay_follows_risk_adjusted_excess_return():
    """In a falling market, holding cash beats the benchmark and is paid; a fully invested holder trails it and
    isn't, and its purse runs down."""
    w = society([Community("sitter", 2, {"risk"}, Sitter()), Community("holder", 2, {"execution"}, Holder())],
                drift=-0.002)
    paid = {c: sum(s["paid"] for s in w.desk.settlements if s["coop"] == c) for c in ("sitter", "holder")}
    assert paid["sitter"] > 0 and paid["holder"] == 0
    assert w.ledger.balance(purse("sitter")) > w.ledger.balance(purse("holder"))
    assert len([s for s in w.desk.settlements if s["coop"] == "sitter"]) == 2  # cycles 24 and 48
    w.ledger.check()


def test_a_model_backed_desk_trades_through_the_tools():
    backend = FakeBackend(respond=lambda *a: GOOD_GRADE, converse=competent)
    llm = Community("trend", 3, {"signal"}, LLMStrategy(backend, steward_model="fake", member_model="fake"))
    w = society([llm], cycles=3)
    bought = [e for e in w.activity.recent(100) if e.community == "trend" and e.name == "buy"]
    assert bought and bought[0].ok and bought[0].actor == "steward"
    assert w.desk.accounts["trend"].positions


def test_the_trading_pack_runs_with_its_own_population_and_scorecard():
    pack = load("trading")
    w = World(Params(**{**pack.params, "seed": 3}), pack=pack).run(30)
    keys = {m["key"] for m in w.scorecard}
    assert {"excess", "drawdown", "sortino", "fees", "limit_stops"} <= keys
    assert w.jobs == {} and len(w.desk.settlements) == 4  # no job board; four desks settled at cycle 24


def test_the_live_pack_uses_live_prices_and_pays_more_per_point():
    pack = load("trading")
    live, fake = pack.live_desk(0), pack.desk(0)
    assert type(live.market).__name__ == "LiveMarket" and type(fake.market).__name__ == "FakeMarket"
    assert live.per_return > fake.per_return
    assert replace(pack).name == "trading"


def test_kernel_actions_the_society_lacks_are_not_offered_and_refused_by_rule():
    seen = {}

    def steward(system, messages, tools):
        seen["tools"] = {t["name"] for t in tools}
        if len([m for m in messages if m["role"] == "assistant"]) == 0:
            return {"tool_calls": [("publish", {"capability": "risk", "title": "t", "text": "x"})]}
        return {"tool_calls": [("end_turn", {})]}

    llm = Community("trend", 3, {"risk"}, LLMStrategy(FakeBackend(converse=steward)))
    w = society([llm], cycles=1)
    assert {"buy", "sell", "raise_stop", "note", "end_turn"} <= seen["tools"]
    assert not seen["tools"] & {"claim", "publish", "propose_venture", "commission", "fork", "search_archive"}
    refused = [e for e in w.activity.recent(20) if e.name == "publish"]
    assert refused and not refused[0].ok and "this society has no publish" in refused[0].text
    assert w.library == {}


def test_a_refused_buy_says_how_much_would_fit():
    w = society([Community("sitter", 2, {"risk"}, Sitter())], cycles=1)
    from commons.application.actions import Actions

    out = Actions(w, w.communities["sitter"]).desk_call("buy", {"symbol": "BTC-USD", "amount": 2_500, "stop_pct": 0.1})
    assert not out and "at most 2,000.00 more" in out.message
