"""Sign in to Etsy once, to get the OAuth tokens the store's Etsy channel uses (it refreshes them by itself after).

    uv run python -m packs.storefront.etsy_login

Before you run it: in your Etsy app's settings (etsy.com/developers/your-apps), add the redirect URL
http://localhost:3003/callback, and put ETSY_KEYSTRING in .env. The script opens Etsy's sign-in page in your browser
(OAuth 2.0 with PKCE, scopes listings_r listings_w transactions_r), waits for Etsy to send you back to that local
address, swaps the code for tokens and writes them to runs/etsy-token.json (git-ignored), where the channel reads
them. Add ETSY_SHOP_ID and ETSY_TAXONOMY_ID to .env too, then `commons channels --pack storefront --check`.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import secrets as random_tokens
import sys
import urllib.parse
import webbrowser
from pathlib import Path

from commons.adapters import secrets
from packs.storefront.live_channels import EtsyChannel, urllib_transport

REDIRECT = "http://localhost:3003/callback"
SCOPES = "listings_r listings_w transactions_r"
TOKEN_FILE = Path("runs/etsy-token.json")


def authorize_url(keystring: str, state: str, verifier: str) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return "https://www.etsy.com/oauth/connect?" + urllib.parse.urlencode({
        "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES, "client_id": keystring, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


def exchange(keystring: str, code: str, verifier: str, transport=urllib_transport) -> dict:
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "client_id": keystring, "redirect_uri": REDIRECT,
                                   "code": code, "code_verifier": verifier}).encode()
    status, data = transport("POST", EtsyChannel.TOKEN, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status >= 400:
        raise SystemExit(f"Etsy refused the code ({status}): {data[:200]!r}")
    return json.loads(data)


def wait_for_code(state: str) -> str:
    """One request to the local callback: Etsy's redirect, carrying the code."""
    got: dict = {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (the stdlib's name)
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            got.update(code=(q.get("code") or [""])[0], state=(q.get("state") or [""])[0], error=(q.get("error") or [""])[0])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab and go back to the terminal.")

        def log_message(self, *a):
            pass

    http.server.HTTPServer(("localhost", 3003), Callback).handle_request()
    if got.get("error") or got.get("state") != state or not got.get("code"):
        raise SystemExit(f"sign-in didn't complete: {got.get('error') or 'state mismatch or no code'}")
    return got["code"]


def main() -> None:
    secrets.load_env()
    keystring = secrets.get("ETSY_KEYSTRING")
    if not keystring:
        sys.exit("put ETSY_KEYSTRING in .env first (see .env.example)")
    state, verifier = random_tokens.token_urlsafe(16), random_tokens.token_urlsafe(48)
    url = authorize_url(keystring, state, verifier)
    print(f"Opening Etsy's sign-in page. If it doesn't open, visit:\n{url}")
    webbrowser.open(url)
    tokens = exchange(keystring, wait_for_code(state), verifier)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"access": tokens["access_token"], "refresh": tokens["refresh_token"]}))
    print(f"Signed in: tokens written to {TOKEN_FILE}. Set ETSY_ACCESS_TOKEN=from-file in .env (any value: the file wins).")


if __name__ == "__main__":
    main()
