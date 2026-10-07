# Phase 2: one real channel (digital products), pack 0 goes live

Your decisions (5 Oct):
1. **What:** online digital products for the MAGA and evangelical Christian audience: devotionals, Bible reading
   plans, study guides, scripture cards, prayer planners, printable verse and patriotic art, civics and American
   history packs, homeschool worksheets.
2. **Where:** combinations: one product can be listed on several channels at once. Each channel is an adapter behind
   one sales port, and the ledger records every sale by channel.
3. **Charters:** a co-op can't change its own charter without your approval. It files a request for comment: other
   co-ops comment for a fixed number of cycles, then the proposal comes to your gate.
4. **Dropping a product** requires the gate too. Kill criteria never drop anything themselves: they raise a drop
   request with the reason and the numbers, and you decide.

5. **Prices** (6 Oct): at least $5, aiming well above with bundles and packs (up to $49.99). **Typst** typesets
   every PDF (US Letter and A4) and cover; **every listing discloses AI use**. How each sale earns: `docs/REVENUE.md`.
6. **Kill criteria** (7 Oct), counted in calendar days (the wall clock live, not cycles), each only a request to you:
   - **a product** raises a drop request when it has had **no sale for 60 days**; when **at least 3 of its sales, and
     more than 20%, were refunded**; when **a channel took it down** (Etsy or Lemon Squeezy shows it gone, inactive
     or unpublished); or when it **no longer passes the store's rules** (listed products are re-screened daily, so a
     tightened rule reaches what's already listed)
   - **the store** raises a pause request (the gate's govern class) when **nothing has sold for 90 days**, or when
     its **real spend beat its real sales after fees by more than $25 over the last 30 days** (spend: model calls,
     illustrations, and Etsy's $0.20 listing fee, now booked as a real bill)
   - **after you deny** one, the rules wait **30 days** before asking again (one that expires unanswered may be asked
     again next cycle); an approved pause writes the society's `paused` file (`commons resume NAME` undoes it)

Done when (CHECKLIST.md): the first real dollar settles through the ledger.

## Rules (code, not prompts; the earn-online pack's screen, as OSINT's is)

1. No real people's names, likenesses or trademarks, and nothing that poses as, or implies endorsement by, a real
   person, church, ministry or campaign. "Make America Great Again" is a registered trademark.
2. No factual claims about elections, candidates or current events: products are devotional, inspirational,
   educational or decorative.
3. No health, financial or "prayer guarantees results" claims; no fake urgency or scarcity.
4. Nothing attacking or demeaning other groups.
5. Scripture from public-domain translations only (KJV, WEB) unless a licence is added.
6. Every listing, price change and drop goes through the gate; nothing public happens without your approval.

## Design

- **Products** are the work: a co-op designs a product (title, description, the files, a price, the channels), and
  the parts are graded like any job (the pack's rubrics, the screen above, formats).
- **The publish tool** is the gate's first "publish" risk class: a listing is a request with everything that would
  go public (text, images, price, channels); nothing reaches a channel until you approve it, as with web reads.
- **Sales port and adapters:** list, update price, unlist, and fetch sales and refunds. A fake channel for tests and
  dry runs; real ones (Etsy, Lemon Squeezy, Stripe payment links) behind the same port, each with test-mode keys
  first where the channel has a test mode.
- **Money:** real sales arrive in USD (the live society is real money end to end); the ledger books revenue per
  channel, fees and refunds; the real-dollar caps still apply to spending.
- **Requests for comment** (kernel): a proposal type for charter changes with a comment window, then the gate.
- **Drop and pause requests:** the kill criteria (decision 6) raise them; the gate decides. Code:
  `packs/storefront/desk.py` (the constants at the top), tests in `tests/storefront/test_store.py`.

## Stages

- [ ] P2.0 Plan (this), and the accounts: which channels you'll open, and their test-mode keys
- [x] P2.1 The screen for these rules, red-teamed (trademarks, endorsements, election claims, health and money claims,
      urgency, attacks, copyrighted translations)
- [x] P2.2 Products as work: brief, product types, rubrics, formats, calibration cases
- [x] P2.3 The gate's publish class: listing requests, batch approval in the console and `commons approve`
- [x] P2.4 The sales port, a fake channel, and the ledger's sales, fees and refunds by channel
- [x] P2.5 Requests for comment: charter changes with a comment window, then the gate
- [x] P2.6 Kill criteria as drop requests to the gate; settled 7 Oct (decision 6): 60 quiet days, refunds,
      takedowns, the rules re-checked daily, a 30-day wait after a denial, and store-wide pause requests
- [~] P2.7 Built and tested against fakes (6 Oct); waiting for your keys. Product files typeset in code (PDF and cover);
      FLUX.2 illustrations through BFL as spend requests; Etsy by API (drafts until ETSY_ACTIVATE=yes); Lemon Squeezy
      by hand from a kit, then `commons link` (its API can't create products); real sales booked in USD beside the
      makers' credits. Still to do with your keys: `commons channels --check`, one product end to end on Etsy as a
      draft and on Lemon Squeezy in test mode
- [ ] P2.8 Live: your first approved listing; done when the first real dollar settles
