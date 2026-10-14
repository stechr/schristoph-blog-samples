"""Toy model: how money flows when decision journeys move from search to an
ad-funded answer engine.

ILLUSTRATIVE ONLY. Every parameter below is an assumption chosen to show the
mechanics, not a calibrated market estimate. Change them and re-run.

A "journey" is one commercial-intent decision (e.g. "which savings account").
It happens either in search (ten links + search ads) or in an answer engine
(one synthesized answer + one ad beside it).

Two budget modes answer "is new revenue created or only redistributed?":
  fixed  - advertisers have a fixed total budget; channels compete for it.
  value  - advertisers bid up to value / target ROAS, so CPC follows the value
           a click delivers; total spend can grow if matching gets better.
"""
from dataclasses import dataclass, replace
import argparse, csv, sys

@dataclass
class Params:
    journeys: float = 1e9          # commercial decision journeys per month
    target_roas: float = 1.5       # advertiser wants >= 1.5x conversion value per $ spent
    value_per_conv: float = 60.0   # $ value to the advertiser per conversion
    # search channel
    s_ad_click: float = 0.04       # ad clicks per journey (several ad slots)
    s_ad_conv: float = 0.03        # conversion rate after an ad click
    s_org_click: float = 0.60      # organic clicks to publishers per journey
    # answer-engine channel
    a_eligible: float = 0.80       # share of journeys the guardrail allows ads on
    a_ad_click: float = 0.03       # ad clicks per eligible journey (one ad slot)
    a_ad_conv: float = 0.06        # conversion rate after click (richer intent signal)
    a_org_click: float = 0.08      # citation clicks to publishers per journey
    a_new_moments: float = 0.15    # extra decision journeys per assistant journey that
                                   # never became a search (new inventory)
    # publisher monetization of a referral visit
    pages_per_visit: float = 1.5
    pub_rpm: float = 20.0          # $ display revenue per 1000 pageviews
    pub_aff_conv: float = 0.02     # affiliate conversion per visit
    pub_aff_commission: float = 3.0

def run(p: Params, shift: float, mode: str) -> dict:
    s_j = p.journeys * (1 - shift)
    a_j = p.journeys * shift * (1 + p.a_new_moments)

    s_clicks = s_j * p.s_ad_click
    a_clicks = a_j * p.a_eligible * p.a_ad_click
    s_value = s_clicks * p.s_ad_conv * p.value_per_conv
    a_value = a_clicks * p.a_ad_conv * p.value_per_conv

    # value mode: CPC = value per click / target ROAS (competitive bidding)
    s_spend = s_value / p.target_roas
    a_spend = a_value / p.target_roas
    if mode == "fixed":
        base_budget = p.journeys * p.s_ad_click * p.s_ad_conv * p.value_per_conv / p.target_roas
        k = base_budget / (s_spend + a_spend)
        s_spend, a_spend = s_spend * k, a_spend * k

    visits = s_j * p.s_org_click + a_j * p.a_org_click
    pub = visits * (p.pages_per_visit * p.pub_rpm / 1000 + p.pub_aff_conv * p.pub_aff_commission)

    return {
        "shift": shift, "mode": mode,
        "search_ad_rev": s_spend, "assistant_ad_rev": a_spend,
        "total_ad_spend": s_spend + a_spend,
        "publisher_rev": pub,
        "advertiser_conv_value": s_value + a_value,
        "advertiser_net": s_value + a_value - s_spend - a_spend,
        "open_web_clicks_per_journey": visits / (s_j + a_j),
    }

def fmt(x): return f"{x/1e6:8.1f}M" if abs(x) >= 1e5 else f"{x:8.3f}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="write all rows to this CSV")
    ap.add_argument("--no-uplift", action="store_true",
                    help="assistant converts no better than search and creates no new moments")
    args = ap.parse_args()
    p = Params()
    if args.no_uplift:
        p = replace(p, a_ad_conv=p.s_ad_conv, a_new_moments=0.0)

    rows = [run(p, s, m) for m in ("fixed", "value") for s in (0.0, 0.2, 0.4, 0.6)]
    cols = list(rows[0].keys())
    print(" | ".join(f"{c:>14}" for c in cols))
    for r in rows:
        print(" | ".join(f"{r[c]:>14}" if isinstance(r[c], str) else f"{fmt(r[c]):>14}" for c in cols))
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)

if __name__ == "__main__":
    sys.exit(main())
