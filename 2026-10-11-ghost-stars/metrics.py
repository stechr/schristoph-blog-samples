"""Rating metrics for Ghost Stars.

Definitions (all shown in the UI):

raw            Google's rating, recomputed from the star histogram (more precise than the 1-decimal header).
calibrated     Lifetime rating if the removed reviews had stayed, each counted as `assumed` stars:
                   (raw * count + assumed * removed) / (count + removed)
               Google shows removals as a range; we return both ends. "über 250" has no upper
               bound, so the upper end is an explicit estimate: max(500, 5 % of count).
recent[w]      Mean stars of visible reviews younger than w months, with sample size n and a
               ~95 % interval. If the loaded reviews do not reach back w months, the window is
               marked partial and `covered_days` says how far the data reaches.
calibrated_12m The notice only counts removals in the last 12 months, so adding them to the
               12-month visible reviews is the fairer comparison:
                   (mean_12m * n_12m + assumed * removed) / (n_12m + removed)
               For busy places we cannot load a full year of reviews; n_12m is then estimated
               from the review rate in the loaded window (reviews per day * 365) and flagged.
"""
from __future__ import annotations

import math

MONTH = 30.4


def _adjust(mean: float, n: float, removed: float, assumed: float) -> float:
    return (mean * n + assumed * removed) / (n + removed)


def upper_bound(lo: int | None, hi: int | None, count: int) -> tuple[int, bool]:
    """Upper end of the removal range; second value is True if it is our estimate."""
    if hi is not None:
        return hi, False
    return max(500, round(count * 0.05), (lo or 0) * 2), True


def calibrated(raw: float | None, count: int, lo: int | None, hi: int | None, assumed: float):
    if raw is None or not count:
        return None
    if lo is None:
        return {"lo": round(raw, 2), "hi": round(raw, 2), "estimated_upper": False}
    up, est = upper_bound(lo, hi, count)
    return {"lo": round(_adjust(raw, count, up, assumed), 2),
            "hi": round(_adjust(raw, count, lo, assumed), 2),
            "estimated_upper": est}


def window(reviews: list[dict], months: float, oldest_days: float | None):
    days = months * MONTH
    stars = [r["stars"] for r in reviews if r.get("age_days") is not None and r["age_days"] <= days]
    partial = oldest_days is None or oldest_days < days
    if not stars:
        return {"n": 0, "mean": None, "ci95": None, "partial": partial,
                "covered_days": oldest_days}
    n = len(stars)
    mu = sum(stars) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in stars) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "mean": round(mu, 2), "ci95": round(1.96 * sd / math.sqrt(n), 2) if n > 1 else None,
            "partial": partial, "covered_days": oldest_days}


def calibrated_12m(reviews: list[dict], oldest_days: float | None, lo: int | None, hi: int | None,
                   count: int, assumed: float):
    dated = [r for r in reviews if r.get("age_days") is not None]
    if not dated:
        return None
    year = [r["stars"] for r in dated if r["age_days"] <= 365]
    if not year:
        return None
    mean = sum(year) / len(year)
    if oldest_days is not None and oldest_days >= 365:
        n12, estimated = len(year), False
    else:
        span = max(oldest_days or 1, 7)  # avoid absurd rates from a few hours of data
        n12, estimated = len(year) / span * 365, True
    n12 = min(n12, count) if count else n12
    if lo is None:
        return {"lo": round(mean, 2), "hi": round(mean, 2), "n12": round(n12), "n12_estimated": estimated,
                "estimated_upper": False}
    up, est_up = upper_bound(lo, hi, count)
    return {"lo": round(_adjust(mean, n12, up, assumed), 2),
            "hi": round(_adjust(mean, n12, lo, assumed), 2),
            "n12": round(n12), "n12_estimated": estimated, "estimated_upper": est_up}


def buckets(reviews: list[dict], oldest_days: float | None, months: int = 12) -> dict:
    """Average stars per time bucket, oldest first.

    Monthly buckets over the last 12 months when the loaded reviews cover at least 3 months.
    Busy places get hundreds of reviews a month, so their loaded reviews may cover only a few
    weeks; they get weekly buckets for the last four weeks instead. Only fully covered buckets are returned.
    """
    cover = oldest_days or 0
    if cover >= 3 * MONTH:
        size, unit, n_max = MONTH, "month", months
    else:
        # Maps switches from "vor 3 Wochen" to "vor einem Monat" after four weeks, so finer
        # than monthly only works inside the last four weeks.
        size, unit, n_max = 7.0, "week", 4
    n = min(n_max, max(int(cover // size), 1))
    out = []
    for b in range(n):
        lo, hi = b * size, (b + 1) * size
        s = [r["stars"] for r in reviews if r.get("age_days") is not None and lo <= r["age_days"] < hi]
        out.append({"ago": b, "n": len(s), "mean": round(sum(s) / len(s), 2) if s else None})
    return {"unit": unit, "days": size, "buckets": list(reversed(out))}


def trend(series: dict) -> dict | None:
    """Direction of the newest reviews, from a weighted least-squares line through the buckets.

    Weights = reviews per bucket, so a bucket with one review barely moves the line.
    Reported as the change of the fitted line across the shown period (e.g. +0.3 stars over
    12 months or -0.2 stars over 4 weeks), not extrapolated beyond it. A change below
    0.2 stars counts as flat. Needs at least 3 buckets with reviews and 8 reviews in total.
    """
    pts = [(-b["ago"], b["mean"], b["n"]) for b in series["buckets"] if b["mean"] is not None]
    if len(pts) < 3 or sum(w for _, _, w in pts) < 8:
        return None
    sw = sum(w for _, _, w in pts)
    mx = sum(x * w for x, _, w in pts) / sw
    my = sum(y * w for _, y, w in pts) / sw
    sxx = sum(w * (x - mx) ** 2 for x, _, w in pts)
    if not sxx:
        return None
    slope = sum(w * (x - mx) * (y - my) for x, y, w in pts) / sxx
    span = len(series["buckets"])
    change = slope * (span - 1)
    direction = "up" if change >= 0.2 else "down" if change <= -0.2 else "flat"
    return {"change": round(change, 2), "direction": direction, "points": len(pts),
            "span": span, "unit": series["unit"]}


def summarize(place: dict, assumed: float = 1.0, windows=(1, 2, 3, 6, 12)) -> dict:
    count = place.get("count") or 0
    lo, hi = place.get("removed_lo"), place.get("removed_hi")
    revs = place.get("reviews") or []
    oldest = place.get("oldest_loaded_days")
    raw = place.get("rating")
    out = {
        "raw": raw,
        "count": count,
        "removed": None if lo is None else {"lo": lo, "hi": hi, "text": place.get("notice_text")},
        "removed_share": None if lo is None or not count else round(lo / (count + lo) * 100, 1),
        "calibrated": calibrated(raw, count, lo, hi, assumed),
        "recent": {str(m): window(revs, m, oldest) for m in windows},
        "calibrated_12m": calibrated_12m(revs, oldest, lo, hi, count, assumed),
        "series": (ser := buckets(revs, oldest)),
        "trend": trend(ser),
        "reviews_loaded": len(revs),
        "covered_days": oldest,
        "assumed": assumed,
    }
    return out


if __name__ == "__main__":
    demo = {"rating": 4.0, "count": 341, "removed_lo": 201, "removed_hi": 250,
            "reviews": [{"stars": s, "age_days": d} for s, d in
                        [(4, 6), (5, 20), (1, 40), (5, 70), (2, 100), (5, 182), (1, 365), (5, 400)]],
            "oldest_loaded_days": 400}
    import json
    print(json.dumps(summarize(demo), indent=1, ensure_ascii=False))
