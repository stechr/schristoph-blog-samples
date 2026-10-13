"""Sweeps for the toy model in sim.py.

1. Shift sweep: total ad spend and publisher revenue as the share of journeys that
   moves to the answer engine goes from 0% to 60%, in value mode, with and without
   the answer-engine uplift. Writes sweep.csv and chart.svg (plain SVG, stdlib only).
2. Break-even: the conversion-rate multiple (answer engine vs search) at which total
   ad spend stays flat, with and without new decision moments.

ILLUSTRATIVE ONLY. Same assumptions as sim.py; change them there.
"""
from dataclasses import replace
import argparse, csv

from sim import Params, run

SHIFTS = [i / 100 for i in range(0, 61, 5)]


def scenarios():
    base = Params()
    no_uplift = replace(base, a_ad_conv=base.s_ad_conv, a_new_moments=0.0)
    return {"with uplift": base, "no uplift": no_uplift}


def shift_sweep():
    rows = []
    for name, p in scenarios().items():
        for s in SHIFTS:
            r = run(p, s, "value")
            rows.append({"scenario": name, "shift": s,
                         "total_ad_spend": r["total_ad_spend"],
                         "publisher_rev": r["publisher_rev"]})
    return rows


def break_even(p: Params, shift: float = 0.6, mode: str = "value") -> float:
    """Conversion multiple (a_ad_conv / s_ad_conv) where total ad spend equals the
    0%-shift baseline. Found by bisection so it works for any parameter set."""
    target = run(p, 0.0, mode)["total_ad_spend"]
    lo, hi = 0.1, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2
        q = replace(p, a_ad_conv=p.s_ad_conv * mid)
        if run(q, shift, mode)["total_ad_spend"] < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def svg_chart(rows, path):
    W, H, L, R, T, B = 760, 440, 80, 190, 40, 60
    pw, ph = W - L - R, H - T - B
    ymax = 70e6
    x = lambda s: L + s / 0.6 * pw
    y = lambda v: T + ph - v / ymax * ph
    colors = {"total_ad_spend": "#c8553d", "publisher_rev": "#2e6f95"}
    labels = {"total_ad_spend": "Total ad spend", "publisher_rev": "Publisher revenue"}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           'font-family="Helvetica, Arial, sans-serif" font-size="13">',
           f'<rect width="{W}" height="{H}" fill="#ffffff"/>']
    for v in range(0, 71, 10):
        yy = y(v * 1e6)
        out.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{L+pw}" y2="{yy:.1f}" stroke="#e5e5e5"/>')
        out.append(f'<text x="{L-8}" y="{yy+4:.1f}" text-anchor="end" fill="#555">{v}M</text>')
    for s in (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6):
        out.append(f'<text x="{x(s):.1f}" y="{T+ph+20}" text-anchor="middle" fill="#555">{int(s*100)}%</text>')
    out.append(f'<line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T+ph}" stroke="#333"/>')
    out.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T+ph}" stroke="#333"/>')
    out.append(f'<text x="{L+pw/2}" y="{H-14}" text-anchor="middle" fill="#333">'
               'Share of decision journeys moved from search to the answer engine</text>')
    out.append(f'<text x="18" y="{T+ph/2}" text-anchor="middle" fill="#333" '
               f'transform="rotate(-90 18 {T+ph/2})">$ per month (toy model)</text>')
    base = rows[0]["total_ad_spend"]
    out.append(f'<line x1="{L}" y1="{y(base):.1f}" x2="{L+pw}" y2="{y(base):.1f}" '
               'stroke="#999" stroke-dasharray="2 4"/>')
    out.append(f'<text x="{L+pw-4}" y="{y(base)-6:.1f}" text-anchor="end" fill="#777" font-size="12">'
               'break-even: ad spend at 0% shift</text>')
    ly = T + 10
    for metric in ("total_ad_spend", "publisher_rev"):
        for scen, dash in (("with uplift", ""), ("no uplift", ' stroke-dasharray="7 5"')):
            pts = " ".join(f"{x(r['shift']):.1f},{y(r[metric]):.1f}"
                           for r in rows if r["scenario"] == scen)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{colors[metric]}" '
                       f'stroke-width="2.5"{dash}/>')
            out.append(f'<line x1="{L+pw+16}" y1="{ly}" x2="{L+pw+44}" y2="{ly}" '
                       f'stroke="{colors[metric]}" stroke-width="2.5"{dash}/>')
            out.append(f'<text x="{L+pw+50}" y="{ly+4}" fill="#333" font-size="12">{labels[metric]}</text>')
            out.append(f'<text x="{L+pw+50}" y="{ly+18}" fill="#777" font-size="11">{scen}</text>')
            ly += 40
    out.append("</svg>")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="sweep.csv")
    ap.add_argument("--svg", default="chart.svg")
    args = ap.parse_args()
    rows = shift_sweep()
    with open(args.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    svg_chart(rows, args.svg)
    p = Params()
    print(f"break-even conversion multiple, no new moments : {break_even(replace(p, a_new_moments=0.0)):.3f}x")
    print(f"break-even conversion multiple, 15% new moments: {break_even(p):.3f}x")
    print(f"wrote {args.csv} and {args.svg}")


if __name__ == "__main__":
    main()
