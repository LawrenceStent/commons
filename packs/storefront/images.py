"""Illustrations for covers: FLUX.2, made on this Mac (mflux, your choice 7 Oct) or through Black Forest Labs' API,
behind the gate either way.

Local (the default when IMAGES=local): FLUX.2 [klein] 4B, Apache 2.0 weights, through mflux (Apple's MLX). No key,
no bill. Each image is its own `mflux-generate-flux2` process, so the model's memory is returned as soon as the
picture is made. Set up once: `uv tool install mflux`, then `mflux-save --model flux2-klein-4b --quantize 4
--path ~/models/flux2-klein-4b-q4` (docs/IMAGES.md).

The API (BFL_API_KEY):

An illustration costs real money, so it is a "spend" request: the maker asks with a prompt, the prompt is screened by
the storefront's rules first (no real people, trademarks or the rest), and nothing is generated until you approve.
The bill goes to the ledger as a real service bill and counts against the daily caps.

    submit   POST https://api.bfl.ai/v1/<model>  {prompt, width, height}  header x-key   ->  {id, polling_url}
    poll     GET polling_url (x-key) until status is Ready                               ->  result.sample (a URL)
    fetch    GET the sample within 10 minutes (signed URLs expire)

Only hosts ending in bfl.ai are ever contacted. Licensing what you sell is yours to check (you, 7 Oct).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from commons.adapters import secrets

# (method, url, headers, body) -> (status, body bytes); tests pass a fake
Transport = Callable[[str, str, dict, bytes | None], tuple[int, bytes]]
API = "https://api.bfl.ai/v1/"
READY = "Ready"  # BFL's task statuses (theirs, not ours)
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
            if status == READY:
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


KLEIN = "flux2-klein-4b"  # the only FLUX.2 checkpoint under Apache 2.0


@dataclass
class LocalFluxImages:
    """FLUX.2 [klein] on this Mac through mflux. `model` is mflux's name for it or the folder `mflux-save` wrote (a
    4-bit copy loads faster and needs well under 10 GB). The seed comes from the prompt, so the same prompt draws
    the same picture."""
    model: str = KLEIN
    steps: int = 4  # klein is distilled for few steps
    price: int = 0  # nothing to pay: the ledger books no bill
    command: str = "mflux-generate-flux2"
    wait: float = 900.0  # the first run loads the model from disk

    def generate(self, prompt: str, width: int = 1440, height: int = 1088) -> bytes:
        exe = shutil.which(self.command) or str(Path.home() / ".local" / "bin" / self.command)
        if not Path(exe).exists():
            raise ImageError(f"{self.command} isn't installed (uv tool install mflux; see docs/IMAGES.md)")
        seed = int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "image.png"
            cmd = [exe, "--model", self.model, "--prompt", prompt, "--width", str(width), "--height", str(height),
                   "--steps", str(self.steps), "--seed", str(seed), "--output", str(out), "--no-exif"]
            if Path(self.model).expanduser().exists():
                cmd[2] = str(Path(self.model).expanduser())
                cmd += ["--base-model", KLEIN]
            try:
                done = subprocess.run(cmd, capture_output=True, text=True, timeout=self.wait)
            except subprocess.TimeoutExpired as e:
                raise ImageError(f"no image after {self.wait:.0f}s") from e
            if done.returncode != 0 or not out.exists():
                raise ImageError(f"mflux failed ({done.returncode}): {(done.stderr or done.stdout)[-300:]}")
            return out.read_bytes()
