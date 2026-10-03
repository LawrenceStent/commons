"""K6/T4: prices. A fake market for tests and the golden master (seeded, deterministic, saved with the society), and
live adapters (Coinbase spot for crypto, Yahoo's chart API for US ETFs and stocks) behind the kernel's egress allowlist. No
network in the suite: the live adapters run against a fake transport."""

import pickle
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from commons.adapters.web import Egress, Fetcher
from packs.trading.prices import CRYPTO, US, FakeMarket, LiveMarket, us_open

NY = ZoneInfo("America/New_York")


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=NY).timestamp()


def test_the_us_market_is_open_on_weekdays_from_9_30_to_4_new_york_time():
    assert us_open(at(2026, 10, 1, 10))  # a Thursday
    assert not us_open(at(2026, 10, 1, 9, 29)) and not us_open(at(2026, 10, 1, 16))
    assert not us_open(at(2026, 10, 3, 12))  # a Saturday


def test_the_fake_market_is_deterministic_and_moves_once_a_cycle():
    a, b = FakeMarket(seed=1), FakeMarket(seed=1)
    for cycle in range(1, 30):
        qa, qb = a.quotes(CRYPTO + US, a.now(cycle)), b.quotes(CRYPTO + US, b.now(cycle))
        assert qa == qb
    again = a.quotes(CRYPTO, a.now(29))
    assert {s: q.price for s, q in again.items()} == {s: qa[s].price for s in CRYPTO}  # same cycle, same prices
    other = FakeMarket(seed=2)
    for cycle in range(1, 30):
        q2 = other.quotes(CRYPTO, other.now(cycle))
    assert q2["BTC-USD"].price != qa["BTC-USD"].price  # another seed, another path


def test_fake_us_quotes_are_stale_and_still_when_their_market_is_shut():
    m = FakeMarket(seed=0)
    closed = [c for c in range(1, 48) if not us_open(m.now(c))]
    assert closed
    before = m.quotes(US, m.now(closed[0] - 1))["SPY"].price
    q = m.quotes(US, m.now(closed[0]))["SPY"]
    assert not q.fresh and (q.price == before or us_open(m.now(closed[0] - 1)))
    assert all(q.fresh for q in m.quotes(CRYPTO, m.now(closed[0])).values())  # crypto never shuts


def test_a_saved_fake_market_carries_on_the_same_path():
    m = FakeMarket(seed=3)
    for c in range(10):
        m.quotes(CRYPTO, m.now(c))
    copy = pickle.loads(pickle.dumps(m))
    assert m.quotes(CRYPTO, m.now(10)) == copy.quotes(CRYPTO, copy.now(10))


def fake_web(responses):
    def transport(url, headers):
        for key, (ctype, body) in responses.items():
            if key in url:
                return 200, {"content-type": ctype}, body.encode()
        return 404, {}, b""
    return Fetcher(Egress(["api.coinbase.com", "query1.finance.yahoo.com"], resolve=lambda h: False), transport=transport)


def yahoo(price, t):
    return ("application/json", f'{{"chart": {{"result": [{{"meta": {{"regularMarketPrice": {price}, '
                                f'"regularMarketTime": {int(t)}}}}}]}}}}')


def test_live_quotes_come_from_coinbase_and_yahoo():
    now = at(2026, 10, 1, 11)  # Thursday, mid-session in New York
    m = LiveMarket(fetcher=fake_web({
        "BTC-USD/spot": ("application/json", '{"data": {"amount": "61234.5", "base": "BTC", "currency": "USD"}}'),
        "chart/SPY": yahoo(571.25, now - 900),
        "chart/QQQ": ("application/json", '{"chart": {"result": null, "error": {"code": "Not Found"}}}'),
    }))
    q = m.quotes(["BTC-USD", "SPY", "QQQ", "ETH-USD"], now)
    assert q["BTC-USD"].price == 61234.5 and q["BTC-USD"].fresh
    assert q["SPY"].price == 571.25 and q["SPY"].fresh
    assert "QQQ" not in q and "ETH-USD" not in q  # no data: no quote (positions keep their last price)


def test_a_us_quote_from_a_shut_market_is_not_fresh():
    m = LiveMarket(fetcher=fake_web({"chart/SPY": yahoo(570.0, at(2026, 10, 2, 16))}))
    q = m.quotes(["SPY"], at(2026, 10, 3, 12))  # Saturday
    assert q["SPY"].price == 570.0 and not q["SPY"].fresh


def test_only_the_price_hosts_are_reachable_and_a_saved_live_market_reconnects():
    m = LiveMarket()
    assert m.fetcher.egress.allow == frozenset({"api.coinbase.com", "query1.finance.yahoo.com"})
    copy = pickle.loads(pickle.dumps(m))
    assert copy.fetcher is not m.fetcher and copy.fetcher.egress.allow == m.fetcher.egress.allow


def test_now_is_the_clock_for_live_and_the_cycle_for_fake():
    import time

    assert abs(LiveMarket().now(5) - time.time()) < 5
    f = FakeMarket()
    assert f.now(3) - f.now(2) == pytest.approx(f.step_seconds)
