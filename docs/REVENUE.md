# Revenue: images and PDFs

How the storefront (Phase 2) can earn, and what each sale leaves after costs. Your decisions (6 Oct): PDFs at a
**minimum of $5**, aiming well above it with bundles and packs; Typst typesets every PDF; every listing discloses AI
use. Fee figures are from memory, not checked today: confirm them against Etsy's and Lemon Squeezy's current fee pages
before relying on them.

Since 7 Oct images are drawn locally (FLUX.2 [klein] 4B through mflux, `docs/IMAGES.md`), so their cost below is $0
unless you switch back to BFL's API. The go-live plan, with what a test costs: `docs/GO-LIVE.md`.

## Costs per sale

| | Etsy | Lemon Squeezy |
|---|---|---|
| Listing | $0.20 per listing, and again each time it sells (auto-renew) | none |
| Transaction | 6.5% of the price | 5% + $0.50 |
| Payment processing | about 3% + $0.25 (US) | included (about +1.5% international or PayPal) |
| Tax | Etsy collects sales tax and VAT | merchant of record: collects and remits tax |
| Optional | Offsite Ads 12-15% on sales they bring (mandatory over $10k a year) | none |

Income tax on what you earn is yours either way.

## PDFs (the core product)

A PDF costs nothing to deliver again, so every sale after the first is almost all margin. Making one is a one-off:
the society's thinking (free on the local model, a few cents to about $0.50 on an API), any illustrations ($0.03 to
$0.50), and Etsy's $0.20 listing fee. A product usually pays for itself on its first sale.

| Price | Etsy keeps | You keep | Lemon Squeezy keeps | You keep |
|---|---|---|---|---|
| $5.00 (the floor) | ~$0.93 | ~$4.07 (81%) | ~$0.75 | ~$4.25 (85%) |
| $9.99 | ~$1.40 | ~$8.59 (86%) | ~$1.00 | ~$8.99 (90%) |
| $19.99 | ~$2.35 | ~$17.64 (88%) | ~$1.50 | ~$18.49 (92%) |
| $29.99 | ~$3.30 | ~$26.69 (89%) | ~$2.00 | ~$27.99 (93%) |

Margin isn't the limit; volume is. Most listings sell little, so what decides profit is findability (titles, tags,
covers), quality, and how much a single purchase is worth. Hence the floor, and the push upward:

- **Bundles beat singles:** a study guide plus memory cards plus a reading plan on one theme, $15-25. Any co-op can
  make one from 2 to 6 existing products, its own or others' (`make_bundle`): one combined PDF, priced at least as
  its dearest part; its sales go 15% to the co-op that assembled it and 85% to the parts' makers by price, so co-ops
  gain by bundling each other's work. Listing it goes through your gate like any product.
- **Packs:** a month of devotionals, a year of verse art, a full VBS (vacation Bible school) kit, $20-40.
- **Editable versions:** Canva or Word templates beside the PDF justify a higher price.

### What we make, and what it needs

| Product | Typical price | Needs |
|---|---|---|
| Bible reading plan (30 or 90 days) | $5-9 | Typst only |
| Prayer planner, stewardship journal | $7-15 | Typst (writing lines, tick boxes) |
| Scripture memory cards (52) | $6-10 | Typst (a card grid to cut) |
| Small-group study guide (4-8 weeks) | $9-19 | Typst (questions, leader notes) |
| Homeschool civics pack (Bill of Rights, the founding) | $8-15 | Typst (worksheets, answer keys) |
| Verse art and founders' quotes sets (6-12 prints) | $8-15 | Typst; optional painted backgrounds (FLUX) |
| Holiday packs (July 4th, Veterans Day, Christmas) | $6-12 | Typst; colouring pages (FLUX line art) |
| Bundles of the above | $15-40 | as their parts |

The typesetter, not an image model, is what makes most of these look worth buying: Typst lays out every page, with
openly licensed fonts, in US Letter and A4.

## Images

### A single image at $1 doesn't pay

| Per $1 sale | Etsy | Lemon Squeezy |
|---|---|---|
| Channel fees | ~$0.55 | ~$0.55 |
| FLUX.2 cost (1-3 tries per keeper, about $0.024-0.048 each) | $0.03-0.15 | $0.03-0.15 |
| **Left** | **~$0.30-0.42** | **~$0.30-0.42** |

The fixed part of the fees eats a $1 sale; the image itself is cheap. Singles are also a weak product: Etsy is full of
them, AI use must be disclosed, and purely AI-made images can't be copyrighted in the US, so anyone can copy them.
Images earn when they're part of something worth more.

### Where images do earn

| Stream | Typical price | Image cost | Notes |
|---|---|---|---|
| Wall art sets (6-12 prints, several sizes) | $8-15 | under $1 a set | the strongest fit: verse art, landscapes, florals |
| Colouring pages (Bible stories, holidays) | $5-10 a pack | $0.30-1 a pack | a strong Etsy category; FLUX draws line art |
| Church media packs (sermon slides, bulletin backgrounds, social graphics) | $10-30 | $0.50-2 | churches buy again each season |
| Monthly devotional subscription with fresh art | $3-7 a month | cents a month | Lemon Squeezy supports subscriptions: recurring income |
| Cover illustrations for our own PDFs | (in the price) | $0.03-0.15 | better covers sell more PDFs |
| Print on demand (posters, canvas, mugs, journals via Printful or Printify) | $15-40 | cents | 20-40% after printing; no stock, but shipping and returns |

Not recommended: selling "commercial use" licences to other sellers (the images can't be protected, and BFL's terms
may not allow it), and stock sites (cents a download).

## Rules that apply to all of it

- Your rules (packs/storefront/screen.py) read every text, listing and illustration prompt: no real people or
  trademarks, nothing about elections, no promises, no pressure, nothing demeaning, KJV or WEB scripture only.
- Every listing says how it was made: written and designed with the help of AI tools (and, if it has one, a cover
  illustration generated by FLUX.2), reviewed by a person before listing.
- Every listing, price change, drop and illustration waits for your approval at the gate.
- Check that BFL's API terms let you sell what FLUX.2 generates.
