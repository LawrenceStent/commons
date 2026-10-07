"""P2.7: FLUX.2 illustrations through BFL's API, against a fake transport (no network, no spend)."""

import json
import pickle

import pytest

from packs.storefront.images import FluxImages, ImageError


def fake(status_after=1, final="Ready", sample="https://delivery-eu1.bfl.ai/x.png"):
    seen, polls = [], {"n": 0}

    def transport(method, url, headers, body):
        seen.append((method, url, headers.get("x-key"), json.loads(body) if body else None))
        if method == "POST":
            return 200, json.dumps({"id": "t1", "polling_url": "https://api.bfl.ai/v1/get_result?id=t1"}).encode()
        if "get_result" in url:
            polls["n"] += 1
            status = final if polls["n"] > status_after else "Pending"
            return 200, json.dumps({"status": status, "result": {"sample": sample}}).encode()
        return 200, b"PNGDATA"
    return transport, seen


def test_submit_poll_and_fetch():
    transport, seen = fake()
    img = FluxImages("k", transport=transport, poll_every=0)
    assert img.generate("a wheat field at dawn, no text") == b"PNGDATA"
    method, url, key, body = seen[0]
    assert (method, url, key) == ("POST", "https://api.bfl.ai/v1/flux-2-klein-9b", "k")
    assert body == {"prompt": "a wheat field at dawn, no text", "width": 1440, "height": 1088}


def test_moderation_and_foreign_hosts_are_errors():
    with pytest.raises(ImageError, match="Content Moderated"):
        FluxImages("k", transport=fake(final="Content Moderated")[0], poll_every=0).generate("x")
    with pytest.raises(ImageError, match="only bfl.ai"):
        FluxImages("k", transport=fake(sample="https://evil.example/x.png")[0], poll_every=0).generate("x")
    with pytest.raises(ImageError, match="BFL_API_KEY"):
        FluxImages("").generate("x")


def test_a_save_keeps_neither_key_nor_transport(monkeypatch):
    monkeypatch.setenv("BFL_API_KEY", "from-env")
    back = pickle.loads(pickle.dumps(FluxImages("secret", model="flux-2-pro", transport=fake()[0])))
    assert back.key == "from-env" and back.model == "flux-2-pro" and b"secret" not in pickle.dumps(back)


def test_local_flux_runs_mflux_once_per_image_with_a_seed_from_the_prompt(tmp_path):
    from packs.storefront.images import KLEIN, LocalFluxImages
    log = tmp_path / "args"
    fake = tmp_path / "mflux-generate-flux2"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nwhile [ $# -gt 0 ]; do [ \"$1\" = --output ] && printf PNG > \"$2\"; shift; done\n")
    fake.chmod(0o755)
    images = LocalFluxImages(str(tmp_path), command=str(fake))  # a saved folder: named with its base model
    assert images.generate("a quiet field at dawn, watercolour") == b"PNG"
    images.generate("a quiet field at dawn, watercolour")
    first, second = log.read_text().splitlines()
    seed = [line.split("--seed ")[1].split()[0] for line in (first, second)]
    assert seed[0] == seed[1] and f"--base-model {KLEIN}" in first and "--steps 4" in first and "--width 1440" in first
    assert images.price == 0


def test_local_flux_says_what_is_missing_or_what_failed(tmp_path):
    import pytest
    from packs.storefront.images import ImageError, LocalFluxImages
    with pytest.raises(ImageError, match="isn't installed"):
        LocalFluxImages(command=str(tmp_path / "nope")).generate("a field")
    broken = tmp_path / "broken"
    broken.write_text("#!/bin/sh\necho out of memory >&2\nexit 3\n")
    broken.chmod(0o755)
    with pytest.raises(ImageError, match="out of memory"):
        LocalFluxImages(command=str(broken)).generate("a field")
