"""The web's sources for investigations (9 Oct): GOV.UK's search API, Tavily's, several joined, and PDFs read page by
page. No test touches the network: fake transports answer."""

import json

import pytest

from commons.adapters.web import (Egress, EgressDenied, Fetcher, GovUkSearch, MultiSearch, TavilySearch, WebAccess,
                                  WebError, searcher)
from commons.domain.gate import GateError, GatePolicy


def pdf(*pages: str) -> bytes:
    """A minimal PDF with one line of text a page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages))) + f"] /Count {len(pages)} >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {5 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def fetcher(pages: dict, hosts=("www.gov.uk", "assets.publishing.service.gov.uk", "api.tavily.com")):
    calls = []

    def transport(url, headers):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return 404, {}, b""
        return pages.get(url.split("?")[0], (404, {}, b""))
    f = Fetcher(Egress(hosts, resolve=lambda h: False), transport=transport)
    f.calls = calls
    return f


def test_a_pdf_is_read_page_by_page_and_a_scan_is_refused():
    url = "https://assets.publishing.service.gov.uk/report.pdf"
    f = fetcher({url: (200, {"content-type": "application/pdf"}, pdf("Spills fell in 2025", "Fines rose"))})
    page = f.fetch(url)
    assert "[page 1]" in page.text and "Spills fell in 2025" in page.text and "[page 2]" in page.text
    assert "Fines rose" in page.text and page.title == "report.pdf"
    scan = fetcher({url: (200, {"content-type": "application/pdf"}, pdf("", ""))})
    with pytest.raises(WebError, match="no text layer"):
        scan.fetch(url)


def test_govuk_search_returns_full_urls_from_its_api():
    api = "https://www.gov.uk/api/search.json"
    body = {"results": [{"title": "Storm overflow assessment framework 2025", "description": "How to assess",
                         "link": "/government/publications/storm-overflow-assessment-framework-2025"}]}
    f = fetcher({api: (200, {"content-type": "application/json"}, json.dumps(body).encode())})
    hits = GovUkSearch(f).search("storm overflows", k=3)
    assert hits[0].url == "https://www.gov.uk/government/publications/storm-overflow-assessment-framework-2025"
    assert "count=3" in f.calls[-1] and "fields=link" in f.calls[-1]


def test_tavily_posts_with_its_key_behind_the_allowlist(monkeypatch):
    sent = []

    def post(url, headers, body):
        sent.append((url, headers, json.loads(body)))
        return 200, json.dumps({"results": [{"title": "Spills report", "url": "https://www.bbc.co.uk/news/x",
                                             "content": "Water firms..."}]}).encode()
    hits = TavilySearch(fetcher({}), key="tvly-test", post=post).search("sewage spills 2025", k=4)
    assert hits[0].url == "https://www.bbc.co.uk/news/x" and sent[0][2]["max_results"] == 4
    assert sent[0][1]["Authorization"] == "Bearer tvly-test"
    with pytest.raises(EgressDenied):
        TavilySearch(fetcher({}, hosts=("www.gov.uk",)), key="k", post=post).search("x")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(WebError, match="TAVILY_API_KEY"):
        TavilySearch(fetcher({}), key=None, post=post).search("x")


class Stub:
    def __init__(self, host, urls=None, error=None):
        self.host, self.urls, self.error = host, urls or [], error

    def search(self, query, k=5):
        from commons.application.ports import SearchResult
        if self.error:
            raise WebError(self.error)
        return [SearchResult(u, u, "") for u in self.urls[:k]]


def test_several_providers_interleave_without_repeats_and_survive_one_failing():
    both = MultiSearch([Stub("www.gov.uk", ["a", "b"]), Stub("api.tavily.com", ["c", "a", "d"])])
    assert [r.url for r in both.search("q", k=3)] == ["a", "c", "b", "d"] and both.host == "www.gov.uk"
    one_down = MultiSearch([Stub("www.gov.uk", error="down"), Stub("api.tavily.com", ["c"])])
    assert [r.url for r in one_down.search("q")] == ["c"]
    with pytest.raises(WebError, match="down"):
        MultiSearch([Stub("www.gov.uk", error="down")]).search("q")


def test_the_gate_takes_providers_joined_with_plus():
    assert GatePolicy.parse({"search": "govuk+tavily"}).search == "govuk+tavily"
    with pytest.raises(GateError, match="search must be"):
        GatePolicy.parse({"search": "govuk+google"})
    access = WebAccess.default("govuk+tavily")
    assert isinstance(access.searcher, MultiSearch) and access.search_host == "www.gov.uk"
    assert searcher("none", access.fetcher) is None and isinstance(searcher("govuk", access.fetcher), GovUkSearch)


def test_a_page_keeps_its_links_documents_first_even_when_its_text_is_cut():
    html = (b"<html><title>Spills</title><body><p>" + b"word " * 5000 + b"</p><a href='/about'>About</a>"
            b"<a href='/media/data.ods'>The data</a><a href='https://x.org/report.pdf'>Report</a>"
            b"<a href='#top'>Top</a><a href='mailto:a@b.c'>Mail</a></body></html>")
    url = "https://www.gov.uk/spills"
    f = fetcher({url: (200, {"content-type": "text/html"}, html)})
    f.max_chars = 2_000
    text = f.fetch(url).text
    links = text.split("Links on this page:\n")[1].splitlines()
    assert links == ["- The data: https://www.gov.uk/media/data.ods", "- Report: https://x.org/report.pdf",
                     "- About: https://www.gov.uk/about"]
    assert len(text) <= 2_000 + 10 and text.startswith("word")
