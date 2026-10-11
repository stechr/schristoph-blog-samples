# Ghost Stars

**The ratings Google's deleted reviews leave behind.**

Companion code for the blog post [Ghost Stars: What a 4.0 Means in Germany](https://schristoph.online/blog/ghost-stars/).

Since April 2026, Google Maps shows a notice on business profiles in Germany when reviews were
removed after defamation complaints, for example *"201 bis 250 Bewertungen aufgrund von
Beschwerden wegen Diffamierung entfernt"*. The notice gives no counterfactual rating; the profile keeps showing Google's current aggregate.
Ghost Stars computes a scenario (what the rating would be if the removed reviews had a star value
you choose) and adds ratings for the most recent months.

> [!IMPORTANT]
> **This is a proof of concept.** It reads the public Google Maps web page with a local
> browser, which can break whenever Google changes the page. Results are scenarios under an
> assumption you choose, not corrected or recovered ratings. It is not affiliated with Google. Use it for personal, low-volume
> lookups and check Google's terms of service before running it at scale or as a service.

## Two ways to use it

| | Calculator (`static/calculator.html`) | Explorer app (`server.py`) |
|---|---|---|
| What it does | Computes a scenario for one place from three numbers you copy from Maps | Scans the places a bounded Maps search returns for a category in an area: map + side-by-side table |
| Runs where | Any browser, static file. Can be embedded in a web page | Your computer only |
| Needs | Nothing | Python via [uv](https://docs.astral.sh/uv/) and Google Chrome |
| Reads Google Maps | No, you type the numbers | Yes, with a local headless Chrome |
| Recent-month ratings | No | Yes (1, 2, 3, 6, 12 months) |

**Why the explorer can't be a static page:** code in a web page can't read the response from
another site unless that site allows it (the browser's cross-origin rules), and Google Maps does
not. A server could fetch the pages, but that would be a scraping service. The Places API
resource I checked does not expose the removal notice either. So the explorer runs locally, with
a real browser under your control.

## No API key needed

Neither part uses a Google API or any key.

- **Google Maps data** comes from the public Maps web page, read by Playwright driving your
  installed Chrome. The official Places API would not help: it returns at most five reviews
  and has no field for the removal notice.
- **Area outlines** come from OpenStreetMap's free [Nominatim](https://nominatim.org/) service
  (one lookup per search, which keeps the request rate low; see its usage policy).
- **Map tiles** come from OpenStreetMap.

## Run the explorer

```bash
./start.sh            # or: uv run --with playwright python server.py
# open http://localhost:8765
```

The first run downloads the Playwright Python package; it uses your installed Google Chrome.
Options (environment variables): `PORT` (default 8765), `PARALLEL` (places read at the same
time, default 3), `HEADED=1` (show the browser, for debugging).

### How it works

```
browser (static/index.html)
   │  1. /api/scan?q=Altstadt, Düsseldorf&cat=Restaurant
   ▼
server.py  (Python standard-library HTTP server, Server-Sent Events)
   ├─ Nominatim: area outline + bounding box            → drawn on the map
   ├─ maps_reader.py (headless Chrome, German Maps UI)
   │    a. search "<category> <area>", collect the result list
   │    b. per place: star histogram, removal notice,
   │       reviews sorted by "newest" (up to 150)
   ├─ metrics.py: Google rating, adjusted rating, recent windows
   └─ cache/places.json (24 h)                          → streamed row by row to the page
```

A scan of 15 places takes about 2–5 minutes the first time. The reader uses the German-language
Maps interface to read business profiles in Germany, where the notice appears; the app itself is in
English. Coverage is limited to the places the Maps search returns and the page loads, the page
selectors can break when Google changes the page, and at most 150 reviews are read per place.

### Cache

Results are stored on your computer in `cache/places.json` for 24 hours, so searching the same
area again is instant. Tick **refresh** in the app to read everything again, or delete the file.
Changing the star assumption never needs a refresh. The cache is in `.gitignore`.

## Method

| Value | Formula / source |
|---|---|
| Google ★ | Average of Google's star histogram |
| Removed | Google's notice; removals processed in the last 365 days (the removed reviews may be older); ranges such as "2 to 5", "201 to 250", top bucket "more than 250" |
| Scenario, lifetime | `(★ × ratings + s × removed) / (ratings + removed)` for both ends of the range; `s` = 1, 2 or 3 stars. The explorer uses the exact histogram; the calculator assumes the displayed rating is a rounded average and takes the star sum as displayed rating × displayed count |
| Scenario, 12 months (EXPERIMENTAL) | Removals processed in the last 365 days added to the visible reviews posted in the last 12 months. Not the same cohort, and limited by the 150-review cap |
| Recent windows | Average of the newest visible reviews in the last 1/2/3/6/12 months, with sample size *n* |
| Trend | Descriptive and sample-limited. Average stars per month over the last 12 months (per week over the last 4 weeks for busy places) from the loaded reviews; empty months are skipped. The arrow is the change of a review-count-weighted line through those averages across the shown period, flat below ±0.2 ★; fewer than 3 periods or 8 reviews shows "too few" |

The table is sortable by every column (click a header, click again to reverse); the default is the Google rating, highest first.

Markers in the app:

- **estimated**: the notice said "more than 250", so the upper end is our estimate
  (the larger of 500, 5 % of the reviews, or twice the lower end).
- **~**: a full year of reviews could not be loaded, so the yearly review count is extrapolated
  from the observed rate.
- *italic*: the loaded reviews do not reach back to the start of that window.

**1 ★ is the minimum-star scenario and 3 ★ the midpoint scenario.** Neither estimates the real,
unknown star values of the removed reviews. Some reviews are removed for good reasons, for example
fake reviews or insults.

## Files

| File | Purpose |
|---|---|
| `static/calculator.html` | Self-contained calculator, no dependencies |
| `static/index.html` | Explorer UI: form, map, sortable table, explanations |
| `server.py` | Local HTTP server, Nominatim lookup, scan stream, cache |
| `maps_reader.py` | Playwright reader for the Maps page; selectors in `SEL` |
| `metrics.py` | Rating calculations (`python metrics.py` runs a demo) |

## Related tools

Browser extensions that show an adjusted rating on the Maps page you are viewing, for example
[Fair Rating](https://github.com/Ennui92/fair-rating-extension) (open source), and a
city-wide scraper, [maps-deleted-reviews](https://github.com/mb4umi/maps-deleted-reviews).
Ghost Stars adds the side-by-side area view and the recent-month ratings.

## License

MIT
