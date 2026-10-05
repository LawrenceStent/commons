"""Illustrations for covers: FLUX.2 through Black Forest Labs' API (your choice, 6 Oct: klein or pro), behind the gate.

An illustration costs real money, so it is a "spend" request: the maker asks with a prompt, the prompt is screened by
the storefront's rules first (no real people, trademarks or the rest), and nothing is generated until you approve.
The bill goes to the ledger as a real service bill and counts against the daily caps.

    submit   POST https://api.bfl.ai/v1/<model>  {prompt, width, height}  header x-key   ->  {id, polling_url}
    poll     GET polling_url (x-key) until status is Ready                               ->  result.sample (a URL)
    fetch    GET the sample within 10 minutes (signed URLs expire)

Only hosts ending in bfl.ai are ever contacted. Check that your BFL plan's terms let you sell what you generate.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from commons.adapters import secrets

# (method, url, headers, body) -> (status, body bytes); tests pass a fake
Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]
API = "https://api.bfl.ai/v1/"
FAILED = ("Error", "Failed", "Content Moderated", "Request Moderated")


class ImageError(Exception):
    pass


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(20_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:2000]
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ImageError(f"couldn't reach {urllib.parse.urlsplit(url).hostname}: {e}") from e


@dataclass
class FluxImages:
    key: str
    model: str = "flux-2-klein-9b"
    price: int = 30_000  # µ$ an image, for the ledger (set BFL_PRICE_PER_IMAGE to your plan's)
    transport: Transport = urllib_transport
    poll_every: float = 1.0
    wait: float = 180.0

    def __getstate__(self) -> dict:  # a saved society keeps neither the key nor the transport
        return {"model": self.model, "price": self.price}

    def __setstate__(self, state: dict) -> None:  # the key comes back from the environment, never from the save
        self.__init__(secrets.get("BFL_API_KEY") or "", state["model"], state["price"])

    def generate(self, prompt: str, width: int = 1440, height: int = 1088) -> bytes:
        if not self.key:
            raise ImageError("no BFL_API_KEY set")
        body = json.dumps({"prompt": prompt, "width": width, "height": height}).encode()
        task = self._json("POST", API + self.model, body)
        poll = str(task.get("polling_url") or "")
        deadline = time.monotonic() + self.wait
        while time.monotonic() < deadline:
            state = self._json("GET", poll, None)
            status = state.get("status")
            if status == "Ready":
                return self._get(str((state.get("result") or {}).get("sample") or ""))
            if status in FAILED:
                raise ImageError(f"the image service refused or failed: {status}")
            time.sleep(self.poll_every)
        raise ImageError(f"no image after {self.wait:.0f}s")

    def _json(self, method: str, url: str, body: bytes | None) -> dict:
        status, data = self._send(method, url, body, {"Content-Type": "application/json"})
        try:
            return json.loads(data)
        except ValueError as e:
            raise ImageError(f"the image service sent something that isn't JSON ({status})") from e

    def _get(self, url: str) -> bytes:
        return self._send("GET", url, None, {})[1]

    def _send(self, method: str, url: str, body: bytes | None, headers: dict) -> tuple[int, bytes]:
        host = urllib.parse.urlsplit(url).hostname or ""
        if urllib.parse.urlsplit(url).scheme != "https" or not (host == "bfl.ai" or host.endswith(".bfl.ai")):
            raise ImageError(f"refusing to contact {host or url[:60]}: only bfl.ai hosts")
        status, data = self.transport(method, url, {**headers, "x-key": self.key, "accept": "application/json"}, body)
        if status >= 400:
            raise ImageError(f"the image service answered {status}")
        return status, data
