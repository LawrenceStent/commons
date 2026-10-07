# Go-live plan: the storefront's first real dollar

The plan is to test the idea for as close to £0 as possible. Lemon Squeezy comes first: test mode, then live, at no
cost until something sells. The model thinks on this Mac (Qwen in LM Studio) and FLUX.2 draws on this Mac (mflux), so
a run costs pennies of electricity. Etsy (about £14 once) waits until the pipeline is proven. Done when the first real
dollar settles through the ledger (P2.8 in `docs/PHASE2-PLAN.md`).

Who does what (your decision, 7 Oct): **you** handle accounts and legalities (FLUX.2's licence, selling AI-made
products, tax as a UK seller). **Claude** handles generation and the code.

## Where to sell

| Channel | Upfront | Per sale | Brings buyers? | Built here? |
|---|---|---|---|---|
| **Lemon Squeezy** (first) | £0 | 5% + 50¢ (+1.5% international or PayPal) | No: you bring the traffic | Yes: a kit, then `commons link` |
| Payhip (free plan) | £0 | 5% + card fees | No | No; would work like Lemon Squeezy |
| Gumroad | £0 | 10% + 50¢; 30% through its Discover page | A little | No |
| Teachers Pay Teachers (basic) | £0 | 45% + 30¢ | Yes: teachers and homeschoolers | No (no seller API; by hand) |
| **Etsy** (later) | about £14 once | ~£0.15 a listing, 6.5%, 4% + 20p, 0.48% | **Yes**: the most search traffic for printables | Yes, by API |

Lemon Squeezy is the merchant of record: it collects and pays sales tax and VAT on each sale. Being free comes with a
catch: it has no marketplace, so a sale needs a link you share (a church group, a Facebook group, social posts).
Etsy is the cheapest test with buyers built in. Teachers Pay Teachers fits the civics and homeschool packs later.
Fees as of Oct 2026, from the sources below; check them before relying on them.

## What a run costs

| Item | Cost |
|---|---|
| Thinking: Qwen 35B in LM Studio, on this Mac | £0 in API fees; about 50 W, so 1-2p of electricity an hour |
| Images: FLUX.2 [klein] 4B through mflux, on this Mac | £0 (`docs/IMAGES.md`) |
| Lemon Squeezy | £0 until something sells |
| Etsy, when you open it | about £14 once, plus ~£0.15 a listing every 4 months (and again at each sale) |
| Anthropic models (optional, not planned) | only with `ANTHROPIC_API_KEY`; capped by `--real-ceiling` ($1 a day by default) |

A 10-product test: **£0 on Lemon Squeezy**, about **£15.50** if you add Etsy. The store's kill criteria still apply:
a pause request if it's more than $25 down in real money over 30 days (decision 6 in `docs/PHASE2-PLAN.md`).

## Stages

### A. Set up (now)
- [ ] **You:** open a Lemon Squeezy account and a store; create a **test-mode** API key. Put `LEMONSQUEEZY_API_KEY`
      and `LEMONSQUEEZY_STORE_ID` in `.env` (copy `.env.example`)
- [ ] **You:** the legal side: FLUX.2 [klein] 4B's Apache 2.0 licence, AI-made products (every listing already
      discloses AI use), what Lemon Squeezy needs from a UK seller to pay out, and HMRC
- [~] **Claude:** local images: mflux installed and the 4-bit model saved to `~/models/flux2-klein-4b-q4`; one test
      cover drawn. `IMAGES=local` in `.env`
- [ ] **Claude:** a storefront society (`commons found`, pack `storefront`) whose operator folder asks you for every
      publish, spend and govern request (`[gate] publish = "ask"`, `spend = "ask"`, `govern = "ask"`)
- [ ] **Claude:** `uv run commons channels --pack storefront --check` shows Lemon Squeezy answering and local images
      ready
- Done when: the check passes and a test image looks right to you

### B. Dry run in test mode (£0)
- [ ] **Claude:** a few cycles on Qwen in LM Studio, at a time that suits you (it runs the machine hard), with
      `uv run commons tick` (`docs/COMMANDS.md`; the exact flags come with the society in stage A)
- [ ] **You:** approve or deny what the society asks for (`uv run commons approve shop`, or the dashboard): covers,
      then listings. Open the PDFs before approving a listing
- [ ] **You:** for each approved listing, create the product in Lemon Squeezy (test mode) from the kit under
      `products/P<n>/`, then `uv run commons link shop P<n> lemonsqueezy <variant id>`
- [ ] **You:** buy one with Lemon Squeezy's test card
- [ ] **Claude:** the next tick books it: a USD sale in the ledger, the maker paid in credits, the sale on the dashboard
- Done when: a test order goes all the way from the society's work to the ledger

### C. Live on Lemon Squeezy (P2.8)
- [ ] **You:** activate the store for live payments (Lemon Squeezy reviews it), then swap in a live-mode API key
- [ ] **You:** recreate the approved products in live mode and link them again (test-mode products don't carry over)
- [ ] **You:** share the product links where the audience is; Lemon Squeezy brings no buyers by itself
- [ ] **Claude:** ticks on a schedule you choose (`commons pace shop MINUTES`; the launchd job stays off until you
      say), with the real-dollar cap and the kill criteria in force
- Done when: the first real dollar settles through the ledger

### D. Etsy (optional, about £14)
- [ ] **You:** open the shop; a UK shop sells in GBP. Create an Etsy app (keystring and shared secret), then sign in:
      `uv run python -m packs.storefront.etsy_login`
- [ ] **You:** in `.env`: `ETSY_CURRENCY=GBP` and `ETSY_USD_RATE` (pounds per dollar, about 0.75). Prices go out
      converted and sales come back in dollars; nothing is listed while `.env` disagrees with the shop's currency
- [ ] **Claude:** `commons channels --check` shows the shop answering and its currency; listings stay drafts
      (`ETSY_ACTIVATE=no`) until you've checked one in Etsy, then `ETSY_ACTIVATE=yes`
- Done when: a listing is live on Etsy and its first sale is booked

## Later
- **Colouring books:** ComfyUI headless, if plain FLUX.2 line art isn't clean enough (`docs/IMAGES.md`)
- **Teachers Pay Teachers or Payhip:** a manual channel like Lemon Squeezy's, about an hour's work each
- **Lemon Squeezy and Stripe:** Stripe owns Lemon Squeezy and runs Stripe Managed Payments at the same fee.
  If Lemon Squeezy is ever folded into it, a Stripe channel joins behind the same sales port

## Sources
Checked 7 Oct 2026:
- [Etsy UK fees (Wise)](https://wise.com/gb/blog/how-to-sell-etsy)
- [Etsy's setup fee](https://linkmybooks.com/blog/how-to-avoid-the-etsy-setup-fee-and-what-it-means-for-your-accounts)
- [Lemon Squeezy's fees](https://dodopayments.com/blogs/lemonsqueezy-review)
- [Lemon Squeezy's free plan](https://costbench.com/software/subscription-billing/lemonsqueezy/free-plan/)
- [Payhip and Gumroad](https://conversionproplus.com/comparison/payhip-vs-gumroad)
- [Gumroad's pricing](https://schoolmaker.com/blog/gumroad-pricing)
- [Teachers Pay Teachers' fees](https://www.tpt.it.com/fees/)
- [FLUX.2 licences](https://invideo.io/blog/flux-ai-image-generator/)
- [mflux](https://github.com/filipstrand/mflux)
