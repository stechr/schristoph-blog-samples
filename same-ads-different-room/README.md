# same-ads-different-room: a toy model of ads moving into AI answers

Companion code for the blog post [Same Ads, Different Room](https://schristoph.online/blog/same-ads-different-room/).

The question it asks: when commercial decisions move from a search results page to an ad-funded answer engine,
does ad revenue grow, or does it only move? And what happens to the publishers who used to get the clicks?

**This is a toy model.** Every parameter is an assumption picked to show the mechanism. None of them is a
market estimate, and the dollar figures are not a forecast. Change the numbers and see which ones drive the result.

## What it models

A "journey" is one commercial decision ("which savings account should I open?"). It happens in one of two places:

- **Search:** several ad slots plus ten organic links. Some clicks go to ads, many go to publishers.
- **Answer engine:** one synthesized answer with one ad next to it, a few citation links, and a guardrail that
  blocks ads on some conversations.

Publishers earn from the visits they receive (display ads per page view plus affiliate commissions).

Two budget modes:

- `fixed`: advertisers have a fixed total budget, and the channels compete for it.
- `value`: advertisers bid up to the value a click delivers divided by their target return on ad spend, so total
  spend grows when the clicks get more valuable.

## Parameters (all assumptions; edit `Params` in `sim.py`)

| Parameter | Default | Meaning |
|---|---|---|
| `journeys` | 1e9 | commercial decision journeys per month |
| `target_roas` | 1.5 | return on ad spend advertisers require |
| `value_per_conv` | 60 | $ value of one conversion to the advertiser |
| `s_ad_click` | 0.04 | ad clicks per search journey (several slots) |
| `s_ad_conv` | 0.03 | conversion rate after a search ad click |
| `s_org_click` | 0.60 | organic clicks to publishers per search journey |
| `a_eligible` | 0.80 | share of answer-engine journeys where ads are allowed |
| `a_ad_click` | 0.03 | ad clicks per eligible answer-engine journey (one slot) |
| `a_ad_conv` | 0.06 | conversion rate after an answer-engine ad click |
| `a_org_click` | 0.08 | citation clicks to publishers per answer-engine journey |
| `a_new_moments` | 0.15 | extra journeys that never would have been a search |
| `pages_per_visit`, `pub_rpm`, `pub_aff_conv`, `pub_aff_commission` | 1.5, 20, 0.02, 3 | publisher monetization of one visit |

## Run it

Python 3.9+ and the standard library only.

```bash
python3 sim.py                    # table for 0/20/40/60% shift, both budget modes
python3 sim.py --no-uplift        # answer engine converts no better than search, no new journeys
python3 sim.py --csv results.csv  # also write the rows to CSV
python3 sweep.py                  # 0-60% sweep (value mode) -> sweep.csv + chart.svg, plus the break-even multiples
```

`sweep.py` finds the break-even conversion multiple by bisection, so it still works after you change the
parameters. With the defaults it prints about 1.67x without new decision moments and about 1.45x with them.

## Things to try

- Raise `a_org_click` until publishers stop losing. With the defaults that happens at about 0.52, nearly as many
  clicks as a full results page.
- Lower `a_ad_conv` to `s_ad_conv` and watch total ad spend fall in value mode.
- Switch between `fixed` and `value` to see who keeps the efficiency gain.

## What it leaves out

Subscriptions, organic visibility effects inside answers, consumer surplus, competition between answer engines,
and any non-linear behaviour. It shows mechanisms, not sizes.

## License

MIT-0. Use it however you like.
