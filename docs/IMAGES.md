# Images: FLUX.2 on this Mac

The storefront's covers and illustrations are drawn by FLUX.2 [klein] 4B on your Mac, through
[mflux](https://github.com/filipstrand/mflux) (Apple's MLX). Your choice (7 Oct): no API bill, and the 4B checkpoint
is the only FLUX.2 model under Apache 2.0. Licensing what you sell is yours to check (you, 7 Oct). The rest of this
page covers making the images.

Every illustration is still a gate request: the maker asks with a prompt, the store's rules screen it, and nothing is
drawn until you approve it. A local image costs nothing, so the ledger books no bill for it.

## Set up (once)

```sh
uv tool install mflux                         # its own environment, outside the project's
mflux-save --model flux2-klein-4b --quantize 4 --path ~/models/flux2-klein-4b-q4
```

`mflux-save` downloads the weights from Hugging Face (about 16 GB, one time), then writes a 4-bit copy. That copy
loads faster and needs well under 10 GB to run. Then, in `.env`:

```sh
IMAGES=local
MFLUX_MODEL=~/models/flux2-klein-4b-q4
```

`uv run commons channels --pack storefront` shows `images (local mflux) ready` when the command is installed.

Try one by hand:

```sh
mflux-generate-flux2 --model ~/models/flux2-klein-4b-q4 --base-model flux2-klein-4b \
  --prompt "watercolour wheat field at dawn, soft light, no text" --width 1440 --height 1088 --steps 4 \
  --seed 1 --output /tmp/test.png
```

## How the store uses it

`packs/storefront/images.py` `LocalFluxImages` runs `mflux-generate-flux2` once per approved image:
- **A fresh process each time.** The model's memory is returned as soon as the picture is made, so keep to one heavy
  thing at a time. Avoid drawing while a large LM Studio model (Qwen 35B, 22 GB) is loaded if the machine is busy.
- **4 steps** (klein is distilled for few), at 1440×1088 for covers.
- **The seed comes from the prompt**, so the same prompt draws the same picture.
- **15 minutes** before giving up. The first image after a restart loads the model from disk.

To go back to the API, unset `IMAGES` and set `BFL_API_KEY`.

## Colouring pages: when ComfyUI is worth it

FLUX.2 draws line art from a prompt ("black and white colouring page, clean outlines, no shading, white background"),
which is enough for simple pages. For colouring books that need more control, ComfyUI is the better tool:
- **Line art from a picture:** lineart or canny ControlNets trace a scene into clean outlines.
- **Consistent characters** across a book's pages (IP-Adapter, reference images).
- **Clean-up passes:** threshold to pure black and white, thicken lines, remove grey fill.

These are node graphs, which mflux doesn't offer. The cost is a heavier install (PyTorch on Apple's GPU, custom
nodes) and more to maintain.

ComfyUI also runs headless, so the store could drive it the same way it drives mflux:
1. Start the server without a browser: `python main.py --listen 127.0.0.1 --port 8188`
2. Build the workflow once in the UI, then save it in API format (Workflow → Export (API)): a JSON graph of nodes.
3. For each image, the store fills in the prompt and seed nodes and POSTs the graph to `/prompt`. That returns a
   `prompt_id`.
4. It polls `/history/<prompt_id>` until the job is done, then fetches the file from `/view?filename=...`.
5. `comfy-cli` (`comfy run --workflow file.json`) wraps the same API for one-off runs.

A `ComfyImages` backend would sit beside `LocalFluxImages` with the same `generate(prompt) -> bytes`. It would only
contact `127.0.0.1`, and each workflow would be a JSON file in the pack. Not built: add it when colouring books are
on the product list and plain FLUX.2 line art isn't clean enough.
