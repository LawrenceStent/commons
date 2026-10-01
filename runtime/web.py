"""The web, for agents: the only way anything in a society reaches the internet (model calls aside).

This is the gate's second enforcement point, independent of the first (sim/gate.py, in the tool layer). Even if
the gate approved something by mistake, this layer refuses:

    - any host not on the egress allowlist (exact, or a subdomain of an entry written "*.example.org")
    - anything but https, IP-literal hosts, and hosts that resolve to private, loopback or link-local addresses
    - redirects to anywhere the allowlist doesn't cover (each hop is checked; at most 3)
    - pages a site's robots.txt disallows for us (search APIs, which are meant for programs, skip robots)
    - anything that isn't text (html, plain, json, xml), and bodies over `max_bytes`

Reads only: GET, no cookies, no credentials, a User-Agent that says what we are. Page text is untrusted: whoever
shows it to a model fences it as reference material.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from html.parser import HTMLParser

from sim.ports import Page, SearchResult, WebError, host_of

USER_AGENT = "CommonsResearchBot/0.1 (a small research simulation; read-only, rate-limited)"
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xml", "text/xml", "application/xhtml+xml")

# (url, headers) -> (status, headers, body). The default is urllib without automatic redirects; tests pass a fake.
Transport = Callable[[str, dict], tuple[int, dict, bytes]]


class EgressDenied(WebError):
    pass


# ── the allowlist ──────────────────────────────────────────────
def _private(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise WebError(f"can't resolve {host}") from e
    for *_, addr in infos:
        ip = ipaddress.ip_address(addr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return True
    return False


class Egress:
    def __init__(self, allow_hosts, resolve: Callable[[str], bool] | None = None):
        self.allow = frozenset(h.lower().strip().rstrip(".") for h in allow_hosts if h.strip())
        self._private = resolve or _private  # tests pass a stub: no DNS in the suite

    def allows_host(self, host: str) -> bool:
        return host in self.allow or any(a.startswith("*.") and (host == a[2:] or host.endswith(a[1:])) for a in self.allow)

    def check(self, url: str) -> str:
        """The url's host, or EgressDenied."""
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme != "https":
            raise EgressDenied(f"only https is allowed ({url[:80]})")
        if not host:
            raise EgressDenied(f"no host in {url[:80]}")
        if parts.username or parts.password:
            raise EgressDenied("urls with credentials are not allowed")
        try:
            ipaddress.ip_address(host)
            raise EgressDenied("addresses must be host names, not IPs")
        except ValueError:
            pass
        if not self.allows_host(host):
            raise EgressDenied(f"{host} is not on the operator's allowlist")
        if self._private(host):
            raise EgressDenied(f"{host} resolves to a private address")
        return host


# ── fetching ───────────────────────────────────────────────────
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None  # we follow redirects ourselves, checking each hop


def urllib_transport(timeout: float = 15.0, max_bytes: int = 2_000_000) -> Transport:
    opener = urllib.request.build_opener(_NoRedirect)

    def send(url: str, headers: dict) -> tuple[int, dict, bytes]:
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read(max_bytes + 1)
        except urllib.error.HTTPError as e:  # 3xx arrive here too, with no redirect handler
            return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, e.read(max_bytes + 1) if e.fp else b""
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise WebError(f"couldn't reach {host_of(url)}: {getattr(e, 'reason', e)}") from e

    return send


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.title, self._skip, self._in_title = [], "", 0, False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    p.feed(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return p.title.strip(), text.strip()


class Fetcher:
    def __init__(self, egress: Egress, transport: Transport | None = None, max_bytes: int = 2_000_000,
                 max_chars: int = 20_000):
        self.egress, self.max_bytes, self.max_chars = egress, max_bytes, max_chars
        self.transport = transport or urllib_transport(max_bytes=max_bytes)
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.requests = 0  # every request that reached the transport, robots.txt included

    def _get(self, url: str) -> tuple[str, dict, bytes]:
        for _ in range(4):
            self.egress.check(url)  # every hop, before anything is sent
            self.requests += 1
            status, headers, body = self.transport(url, {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json"})
            if status in (301, 302, 303, 307, 308) and headers.get("location"):
                url = urllib.parse.urljoin(url, headers["location"])
                continue
            if status >= 400:
                raise WebError(f"{host_of(url)} answered {status}")
            if len(body) > self.max_bytes:
                raise WebError(f"the page at {url[:80]} is larger than {self.max_bytes} bytes")
            return url, headers, body
        raise WebError("too many redirects")

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                _, _, body = self._get(f"{root}/robots.txt")
                rp.parse(body.decode("utf-8", "replace").splitlines())
            except WebError:
                rp.parse([])  # no robots.txt (or unreadable): the site hasn't said no
            self._robots[root] = rp
        return self._robots[root].can_fetch(USER_AGENT, url)

    def fetch(self, url: str, robots: bool = True) -> Page:
        self.egress.check(url)
        if robots and not self._allowed_by_robots(url):
            raise WebError(f"{host_of(url)}'s robots.txt asks bots not to read {urllib.parse.urlsplit(url).path}")
        final, headers, body = self._get(url)
        ctype = headers.get("content-type", "text/html").split(";")[0].strip().lower()
        if ctype not in TEXT_TYPES:
            raise WebError(f"{url[:80]} is {ctype}, not text")
        raw = body.decode("utf-8", "replace")
        title, text = html_to_text(raw) if "html" in ctype else ("", raw)
        return Page(final, title or final, text[: self.max_chars])

    def json(self, url: str) -> dict:
        """A JSON API call (search providers). APIs are meant for programs, so robots.txt doesn't apply."""
        _, _, body = self._get(url)
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise WebError(f"{host_of(url)} didn't return JSON") from e


# ── search ─────────────────────────────────────────────────────
class WikipediaSearch:
    """Search through Wikipedia's public API: free, no key, and its host must still be on the allowlist."""

    def __init__(self, fetcher: Fetcher, lang: str = "en"):
        self.fetcher, self.host = fetcher, f"{lang}.wikipedia.org"

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query[:200], "srlimit": k,
                                    "format": "json", "utf8": 1})
        data = self.fetcher.json(f"https://{self.host}/w/api.php?{q}")
        out = []
        for hit in data.get("query", {}).get("search", [])[:k]:
            title = hit.get("title", "")
            snippet = html.unescape(re.sub(r"<[^>]+>", "", hit.get("snippet", "")))
            out.append(SearchResult(title, f"https://{self.host}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}", snippet))
        return out


class WebAccess:
    """The web port (sim.ports.WebPort): a fetcher behind the allowlist, and an optional search provider. The
    allowlist follows the operator's [gate] policy, re-read every cycle."""

    def __init__(self, fetcher: Fetcher, searcher=None):
        self.fetcher, self.searcher = fetcher, searcher

    @property
    def search_host(self) -> str | None:
        return getattr(self.searcher, "host", None) if self.searcher is not None else None

    def set_hosts(self, hosts) -> None:
        self.fetcher.egress.allow = frozenset(h.lower().strip().rstrip(".") for h in hosts if h.strip())

    def fetch(self, url: str) -> Page:
        return self.fetcher.fetch(url)

    def search(self, query: str, k: int = 5) -> list[SearchResult]:
        if self.searcher is None:
            raise WebError("this society has no web search")
        return self.searcher.search(query, k)

    @classmethod
    def default(cls, search: str = "wikipedia") -> WebAccess:
        fetcher = Fetcher(Egress(()))  # no hosts until the operator allows some
        return cls(fetcher, WikipediaSearch(fetcher) if search == "wikipedia" else None)
