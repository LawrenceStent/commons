# Dashboard redesign: ideas

*Written 26 Sep 2026. Nothing here is built. The current dashboard (`commons/interfaces/console/dashboard.html`) is a plain,
functional page; this is a direction to take it in over time. The rules at the end matter as much as
the look.*

## 1. The look: cyberpunk, but readable

A HUD for a city of agents: dark, dense, neon-lit, with the glow reserved for things that matter.

### Palette (starting point, to be validated)

| Role | Colour | Use |
|---|---|---|
| Background | `#07070d` near-black, `#0d0f1a` panels | Page and panel surfaces |
| Grid and rules | `#1c2035` | Panel borders, axes, gridlines (recessive) |
| Text | `#d8e1ff` primary, `#7f8bb3` secondary | All numbers and labels (never neon) |
| Neon cyan | `#00f0ff` | The primary series; active states; "running" |
| Neon magenta | `#ff2a6d` | Alerts, kill-switch, defaults and failures |
| Acid yellow | `#f5e663` | Warnings, rate limits, pending |
| Neon green | `#3dff9a` | Healthy, paid, accepted |
| Violet | `#9d6bff` | Knowledge and royalties; the second series |
| Real money | a distinct gold `#ffc857` with a `$` | Only ever used for USD, never for credits |

These are guesses. Neon palettes often fail colour-blind checks (magenta against cyan, green against
yellow), so every categorical set goes through the palette validator from the dataviz guidance before
it ships. Status colours always come with an icon or label, never colour alone.

### Type and texture
- A display face for headings (for example **Orbitron** or **Rajdhani** from Google Fonts), and a
  monospace for all numbers (**JetBrains Mono** or **Share Tech Mono**) so figures line up.
- Panels with **clipped corners** (`clip-path` notches), thin neon edges, and a faint inner glow.
- **Scanlines and grain** as a very subtle overlay that you can switch off, and that is off
  automatically when the system asks for reduced motion.
- **Glow means something.** Only live or alarming things glow: the running indicator, a kill-switch, a
  community in trouble. If everything glows, nothing does.
- A **"glitch" moment** (a brief colour split on the banner) when the kill-switch trips or the memory
  guard pauses the run. It happens once, not in a loop.
- Keep a **plain theme** toggle, for long sessions, screenshots and anyone who finds neon tiring.

## 2. More creative ways to show the data

Ordered roughly by how much each would help, not by how flashy it is.

1. **The society as a living network.** Communities are nodes: size is purse, glow is standing,
   rings are members awake. Contracts are edges: thickness is value, colour is outcome. When money
   moves, a pulse travels along the edge. Forks appear as a node splitting; merges as two nodes
   joining. This is the view that makes "no one is in charge" visible, and it shows at a glance if
   one node is becoming a hub (the plan's Failure 2).
2. **Money flow (Sankey).** Market or grant → primes → contractors → treasury → floor, with royalties
   branching to authors and compute burning off the side, for the last N cycles. Shows where the
   money actually goes, which is the question every finding so far has been about. Credits and real
   dollars are never in the same diagram.
3. **Efficiency quadrant.** Each co-op is a dot: x = credits spent thinking, y = value earned, with the
   break-even diagonal drawn. Above the line is good; the trail behind each dot shows its last 50
   cycles. This is the headline for the "effectiveness, not speed" principle.
4. **Scorecard strip** (for mission societies). One bullet chart per scorecard metric, each against
   its target, with hard floors (ethics violations) shown as a separate alarm that is always visible.
   A radar chart is tempting here, but bullet charts are easier to read accurately.
5. **Purses over time as small multiples,** one per co-op on the same scale, with population events
   as glyphs on the timeline (spawn +, fork ⑂, merge ⋈, learn ✦). Easier to compare than one tangled
   chart.
6. **Trust matrix, upgraded.** Keep the heatmap (it's accurate), and add a hover that shows how the
   trust was earned: which contracts, which gossip, how old.
7. **Family tree of communities.** Forks and merges drawn as a genealogy, so you can see which lineages
   thrive.
8. **Contract pipeline as flow.** Columns for open, awarded, delivered, closed, with contracts moving
   across and deadlines shown as shrinking bars. Hoarding and stalling become visible.
9. **Thought trace.** For an LLM turn: a row of chips, one per tool call, green if it worked and
   magenta if refused, with the steward's words and the refusal text on hover. The fastest way to see
   whether a model is actually trading, which is what the 1.5 smoke run needed.
10. **Bus as a data stream.** The message tail as a scrolling terminal, colour-coded by message family,
    with a density sparkline per family. Fun, and genuinely useful for spotting floods.
11. **Replay scrubber.** A timeline slider that replays a finished run from its saved ledger and turn
    log, so any cycle can be inspected after the fact.
12. **Host gauges.** Memory, CPU and the loaded local model as ring gauges, turning magenta near the
    memory guard.
13. **Trading views (when that pack exists).** Equity curve against the benchmark per co-op, drawdown
    underwater chart, exposure, and every stop-loss marked where it fired.

## 3. Rules that keep it honest

- **One axis per chart.** No dual-axis charts; two measures on different scales become two charts.
- **Colour follows the entity, not its rank.** A co-op keeps its colour for its whole life; filters
  never repaint survivors.
- **`$` means real money,** always gold and always labelled. Credits are `cr` and never share a chart
  with dollars.
- **Every chart has a way to read exact values:** hover tooltips, and a table view for anyone who
  wants numbers rather than shapes.
- **Motion is optional.** Pulses, glows and scanlines respect reduced-motion settings, and the page is
  fully usable without them.
- **Cheap to run.** The dashboard must stay within the resource guardrails: canvas rather than
  thousands of DOM nodes for animated views, a cap on points per series (already 120), and no new
  data sent faster than twice a second.

## 4. How to build it, when the time comes

- Stay dependency-light: vanilla JS as now, plus **d3** from a CDN for the network, Sankey and tree
  (d3-force, d3-sankey, d3-hierarchy). No build step.
- Theme through CSS custom properties, which the page already uses, so neon and plain are two sets of
  values, not two stylesheets.
- The snapshot already carries most of the data. The network and Sankey need a small
  "flows in the last N cycles" aggregate on the server, so the browser doesn't rebuild it from raw events.
- Build in this order:
  1. theme
  2. thought trace (it helps 1.5 right away)
  3. efficiency quadrant
  4. money flow
  5. network
  6. the rest
