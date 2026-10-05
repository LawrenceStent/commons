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
- **Drop requests:** the kill criteria (no sale in N days, say) raise them; the gate decides.

## Stages

- [ ] P2.0 Plan (this), and the accounts: which channels you'll open, and their test-mode keys
- [x] P2.1 The screen for these rules, red-teamed (trademarks, endorsements, election claims, health and money claims,
      urgency, attacks, copyrighted translations)
- [x] P2.2 Products as work: brief, product types, rubrics, formats, calibration cases
- [x] P2.3 The gate's publish class: listing requests, batch approval in the console and `commons approve`
- [x] P2.4 The sales port, a fake channel, and the ledger's sales, fees and refunds by channel
- [ ] P2.5 Requests for comment: charter changes with a comment window, then the gate
- [x] P2.6 Kill criteria as drop requests to the gate
- [ ] P2.7 The real channels, test mode first; one product end to end in test mode
- [ ] P2.8 Live: your first approved listing; done when the first real dollar settles
