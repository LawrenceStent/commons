"""Pack 2: trading, on paper (K6 stage 1; docs/K6-PLAN.md).

Co-ops run paper accounts against live prices, crypto and US ETFs and stocks, each by its own doctrine. There is no
job board: the work is the trading, through the desk's tools (packs/trading/desk.py). Every `horizon` cycles each
account is judged against an equal-weight buy-and-hold benchmark, risk-adjusted, and the result is paid in credits
that fund the co-op's thinking (a capital economy): a desk that doesn't beat the benchmark earns nothing and runs
down. The broker's limits (a stop with every buy, a cap per position, no leverage or shorting, a daily loss pause,
a kill criterion) are code, never prompts. Paper only: no account, no real money. Not financial advice.
"""

from commons.domain.community import Community
from commons.domain.pack import Pack, TemplateWorkSource
from commons.domain.scorecard import Metric
from packs.trading.desk import TradingDesk
from packs.trading.prices import CRYPTO, US, FakeMarket, LiveMarket
from packs.trading.scripted import Holder, Momentum, Reckless, Sitter

CAPABILITIES = ("research", "signal", "risk", "execution")

BRIEF = f"""WHAT THIS SOCIETY IS FOR
Trading on paper, to find out which ways of trading actually work, forward in time, after costs and adjusted for risk.
Each co-op runs a paper account of $10,000 by its own doctrine. Nothing here is real money.

THE MARKET
Crypto ({', '.join(CRYPTO)}) trades around the clock. US ETFs and stocks ({', '.join(US)}) trade 9:30 to 16:00 New
York time on weekdays; outside those hours their quotes are marked (closed) and can't be traded. Your desk view shows
quotes, your positions and how this window is going. There is no price history: you see prices as they come, as a
trader would. Don't trade on what you remember of past prices.

HOW YOU ARE PAID
Every window (a fixed number of cycles) your account's return, net of fees and slippage, is compared with a benchmark:
the same money held equally across every symbol from the window's start. You are paid credits for the return above
the benchmark, less half your worst drawdown in the window. Nothing for matching or trailing it. Credits pay for your
thinking: a desk that doesn't beat the benchmark runs out of them and goes quiet. Doing nothing is allowed, and is
sometimes right; so is holding cash.

THE RULES (the world enforces them; orders that break them are refused)
- Every buy carries a stop 1% to 15% below the fill, which sells by itself. Stops can be raised, never lowered.
- At most 20% of your account in any one symbol. No leverage, no margin, no shorting.
- Down 3% in a day: everything is sold and trading pauses until the next day.
- Down 20% of your capital: everything is sold and your desk stops trading for good.
"""

DOCTRINES = {
    "trend": ("A crypto momentum desk: rides moves that are already under way in BTC, ETH and SOL.",
              "Buy what has risen over the last few cycles and is still rising; sell when it turns. Small positions "
              "(5-10%), tight stops (3-5%), raised as a trade goes your way. Cash is a position."),
    "reversion": ("A US mean-reversion desk: buys sharp falls in large ETFs and stocks, sells the bounce.",
                  "Only SPY, QQQ, AAPL, MSFT, NVDA, only while their market is open. Buy after an unusually sharp "
                  "fall, sell into the recovery; never add to a loser. Positions up to 15%, stops 5-8%."),
    "steady": ("A cautious allocator across both markets: a few diversified positions, changed rarely.",
               "Hold 3-5 positions across crypto and US, each 10-18%, stops 10-15%. Rebalance only when a position "
               "drifts far from its weight. Trades cost money: the fewer, the better."),
}


def _population() -> list[Community]:
    return [Community("holder", 2, {"execution"}, Holder()), Community("momentum", 2, {"signal", "execution"}, Momentum()),
            Community("sitter", 2, {"risk"}, Sitter()), Community("reckless", 2, {"execution"}, Reckless())]


def _live_population(llm) -> list[Community]:
    """Three model-backed desks with their doctrines, and a scripted holder as a control."""
    out = []
    for name, (charter, doctrine) in DOCTRINES.items():
        c = llm(name, set(CAPABILITIES), charter, 3, doctrine)
        c.doctrine = doctrine
        out.append(c)
    return out + [Community("holder", 2, {"execution"}, Holder())]


def _settled(w) -> list[dict]:
    return w.desk.settlements if w.desk else []


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


SCORECARD = (
    Metric("excess", "Return above benchmark", lambda w: _mean([s["excess"] for s in _settled(w)]), unit="%",
           target=0.0, what="mean per window, after costs"),
    Metric("drawdown", "Worst drawdown", lambda w: max((s["drawdown"] for s in _settled(w)), default=None),
           better="down", unit="%", what="the worst fall from a peak in any window"),
    Metric("sortino", "Sortino ratio", lambda w: _mean([s["sortino"] for s in _settled(w)]),
           what="mean per window: return per unit of downside"),
    Metric("fees", "Fees paid", lambda w: round(sum(a.fees for a in w.desk.accounts.values()), 2) if w.desk else None,
           better="down", what="paper dollars, every desk"),
    Metric("limit_stops", "Limits that fired", lambda w: w.desk.stops_fired if w.desk else None, better="down",
           what="daily-loss pauses and kill criteria met"),
)

PACK = Pack(
    name="trading",
    title="Trading (paper)",
    brief=BRIEF,
    capabilities=CAPABILITIES,
    work_source=TemplateWorkSource(("the market",), {c: (f"{c} for {{subject}}", "unused: no jobs") for c in CAPABILITIES}),
    population=_population,
    live_population=_live_population,
    params={"jobs_per_cycle": 0, "treasury_seed": 50_000_000},
    live_params={"jobs_per_cycle": 0, "treasury_seed": 50_000_000},
    scorecard=SCORECARD,
    desk=lambda seed: TradingDesk(FakeMarket(seed=seed)),
    # live: a window's thinking costs a model-backed desk about 1-2M µcr, so a point of score (1% of risk-adjusted
    # excess return) pays about that
    live_desk=lambda seed: TradingDesk(LiveMarket(), per_return=200_000_000),
)
