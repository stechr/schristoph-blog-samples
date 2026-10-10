"""Google Maps reader for Ghost Stars.

Reads only what a visitor sees on the public Maps web page:
  * search results for "<category> in <region>"
  * per place: name, coordinates, star histogram, the German defamation-removal
    notice, and the newest reviews (stars + relative date)

It runs a local headless Chrome (Playwright, channel="chrome"). Google can change the
page at any time; all selectors are kept in one place (SEL) to make fixes easy.
"""
from __future__ import annotations

import asyncio
import re
import time
import urllib.parse
from dataclasses import dataclass, field, asdict

from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PWTimeout

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

SEL = {
    "consent": ["Alle akzeptieren", "Accept all"],
    "place_link": 'a[href*="/maps/place/"]',
    "feed": 'div[role="feed"]',
    "reviews_tab": re.compile(r"^Rezensionen"),
    "histogram": 'tr[role="img"][aria-label]',
    "sort_button": 'button[aria-label="Rezensionen sortieren"]',
    "sort_newest": re.compile(r"Neueste"),
    "review": "div[data-review-id][jsaction]",
    "review_stars": 'span[role="img"][aria-label*="Stern"]',
    "review_date": 'span:text-matches("^(vor |Bearbeitet)")',
}

NOTICE_RE = re.compile(
    r"((?:über|mehr als)\s*\d[\d.]*|\d[\d.]*\s*bis\s*\d[\d.]*|\d[\d.]*)\s+Bewertung(?:en)?\s+"
    r"aufgrund von Beschwerden wegen Diffamierung entfernt", re.I)
COORD_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
AGE_UNITS = [("minute", 0), ("stunde", 0), ("tag", 1), ("woche", 7), ("monat", 30.4), ("jahr", 365)]


def _int(s: str) -> int:
    return int(s.replace(".", "").replace(" ", ""))


def parse_notice(text: str | None) -> tuple[int, int | None] | None:
    """'201 bis 250' -> (201, 250); 'über 250' -> (251, None); '3' -> (3, 3); no notice -> None."""
    if not text:
        return None
    t = text.lower()
    m = re.search(r"(\d[\d.]*)\s*bis\s*(\d[\d.]*)", t)
    if m:
        return _int(m[1]), _int(m[2])
    m = re.search(r"(?:über|mehr als)\s*(\d[\d.]*)", t)
    if m:
        return _int(m[1]) + 1, None
    m = re.search(r"(\d[\d.]*)", t)
    return (_int(m[1]), _int(m[1])) if m else None


def parse_age_days(text: str | None) -> float | None:
    """'vor 6 Tagen' / 'Bearbeitet: vor einem Jahr' -> approx. age in days."""
    if not text:
        return None
    t = text.lower().replace("\xa0", " ")
    t = re.sub(r"\b(einem|einer|eine)\b", "1", t)
    m = re.search(r"vor\s+(\d+)\s+([a-zäöü]+)", t)
    if not m:
        return None
    n, unit = int(m[1]), m[2]
    for key, days in AGE_UNITS:
        if unit.startswith(key):
            return n * days
    return None


@dataclass
class Review:
    id: str
    stars: int
    age_days: float | None
    date_text: str


@dataclass
class Place:
    name: str
    url: str
    lat: float | None = None
    lng: float | None = None
    category: str = ""
    rating: float | None = None
    histogram: dict[int, int] = field(default_factory=dict)
    count: int = 0
    notice_text: str | None = None
    removed_lo: int | None = None
    removed_hi: int | None = None
    reviews: list[Review] = field(default_factory=list)
    oldest_loaded_days: float | None = None
    error: str | None = None
    fetched_at: float = 0.0

    def to_json(self) -> dict:
        d = asdict(self)
        d["histogram"] = {str(k): v for k, v in self.histogram.items()}
        return d


class MapsReader:
    def __init__(self, headless: bool = True, parallel: int = 3):
        self.headless = headless
        self.sem = asyncio.Semaphore(parallel)
        self._pw = None
        self._browser: Browser | None = None
        self._ctx = None
        self._consented = False
        self._lock = asyncio.Lock()

    async def _context(self):
        async with self._lock:
            if self._ctx is None:
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(channel="chrome", headless=self.headless)
                self._ctx = await self._browser.new_context(
                    locale="de-DE", user_agent=UA, viewport={"width": 1400, "height": 1000})
        return self._ctx

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._ctx = self._browser = self._pw = None

    async def _consent(self, page: Page):
        if "consent.google" not in page.url and self._consented:
            return
        for label in SEL["consent"]:
            btn = page.get_by_role("button", name=label)
            if await btn.count():
                await btn.first.click()
                await page.wait_for_timeout(2500)
                break
        self._consented = True

    async def search(self, query: str, lat: float, lng: float, zoom: int, limit: int = 20) -> list[Place]:
        """Places from the Maps result list for `query` around (lat, lng)."""
        ctx = await self._context()
        page = await ctx.new_page()
        try:
            url = (f"https://www.google.com/maps/search/{urllib.parse.quote_plus(query)}"
                   f"/@{lat},{lng},{zoom}z?hl=de")
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            await self._consent(page)
            try:
                await page.wait_for_selector(SEL["place_link"], timeout=15000)
            except PWTimeout:
                return []  # nothing found, or a single place page opened directly
            seen: dict[str, Place] = {}
            stale = 0
            while len(seen) < limit and stale < 3:
                links = page.locator(SEL["place_link"])
                before = len(seen)
                for i in range(await links.count()):
                    a = links.nth(i)
                    href = await a.get_attribute("href") or ""
                    name = (await a.get_attribute("aria-label") or "").strip()
                    key = href.split("?")[0]
                    if not name or key in seen:
                        continue
                    m = COORD_RE.search(href)
                    seen[key] = Place(name=name, url=href,
                                      lat=float(m[1]) if m else None, lng=float(m[2]) if m else None)
                stale = stale + 1 if len(seen) == before else 0
                feed = page.locator(SEL["feed"])
                if await feed.count():
                    await feed.first.evaluate("el => el.scrollBy(0, el.scrollHeight)")
                await page.wait_for_timeout(1500)
            return list(seen.values())[:limit]
        finally:
            await page.close()

    async def place(self, p: Place, max_reviews: int = 150, until_days: float = 400) -> Place:
        """Fill rating, histogram, notice and newest reviews for one place."""
        async with self.sem:
            ctx = await self._context()
            page = await ctx.new_page()
            try:
                await self._read_place(page, p, max_reviews, until_days)
            except Exception as e:  # keep the batch going; report per place
                p.error = f"{type(e).__name__}: {str(e)[:160]}"
            finally:
                p.fetched_at = time.time()
                await page.close()
            return p

    async def _read_place(self, page: Page, p: Place, max_reviews: int, until_days: float):
        url = p.url + ("&" if "?" in p.url else "?") + "hl=de"
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        await self._consent(page)
        await page.wait_for_selector("h1", timeout=15000)
        m = COORD_RE.search(page.url) or COORD_RE.search(p.url)
        if m and p.lat is None:
            p.lat, p.lng = float(m[1]), float(m[2])

        cat = page.locator('button[jsaction*="category"]')
        if await cat.count():
            p.category = (await cat.first.inner_text()).strip()

        tab = page.get_by_role("tab", name=SEL["reviews_tab"])
        if not await tab.count():
            p.error = "Google served a limited view without reviews"
            return
        await tab.first.click()
        await page.wait_for_selector(SEL["histogram"], timeout=10000)

        hist = page.locator(SEL["histogram"])
        for i in range(await hist.count()):
            lab = (await hist.nth(i).get_attribute("aria-label") or "").replace("\xa0", " ")
            mm = re.match(r"\s*(\d)\s*Stern\w*,\s*([\d.]+)", lab)
            if mm:
                p.histogram[int(mm[1])] = _int(mm[2])
        p.count = sum(p.histogram.values())
        if p.count:
            p.rating = round(sum(k * v for k, v in p.histogram.items()) / p.count, 2)

        main_text = await page.locator('div[role="main"]').first.inner_text()
        nm = NOTICE_RE.search(main_text.replace("\xa0", " "))
        if nm:
            p.notice_text = nm[0]
            lo_hi = parse_notice(nm[1])
            if lo_hi:
                p.removed_lo, p.removed_hi = lo_hi

        await self._sort_newest(page)
        await self._load_reviews(page, p, max_reviews, until_days)

    async def _sort_newest(self, page: Page):
        btn = page.locator(SEL["sort_button"])
        for _ in range(3):
            if not await btn.count():
                await page.wait_for_timeout(1000)
                continue
            await btn.first.click()
            item = page.get_by_role("menuitemradio", name=SEL["sort_newest"])
            try:
                await item.first.wait_for(timeout=4000)
                await item.first.click()
                await page.wait_for_timeout(2500)
                return
            except PWTimeout:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(800)
        raise RuntimeError("Could not sort reviews by newest")

    async def _load_reviews(self, page: Page, p: Place, max_reviews: int, until_days: float):
        got: dict[str, Review] = {}
        stale = 0
        while len(got) < max_reviews and stale < 3:
            revs = page.locator(SEL["review"])
            n = await revs.count()
            before = len(got)
            for i in range(n):
                r = revs.nth(i)
                rid = await r.get_attribute("data-review-id")
                if not rid or rid in got:
                    continue
                st = r.locator(SEL["review_stars"])
                dt = r.locator(SEL["review_date"])
                if not await st.count() or not await dt.count():
                    continue  # nested duplicate container without own data
                sm = re.match(r"(\d)", (await st.first.get_attribute("aria-label") or ""))
                dtext = (await dt.first.inner_text()).strip()
                if not sm:
                    continue
                got[rid] = Review(id=rid, stars=int(sm[1]), age_days=parse_age_days(dtext), date_text=dtext)
            ages = [r.age_days for r in got.values() if r.age_days is not None]
            if ages and max(ages) > until_days:
                break
            stale = stale + 1 if len(got) == before else 0
            if n:
                await revs.nth(n - 1).scroll_into_view_if_needed()
            await page.wait_for_timeout(1300)
        p.reviews = list(got.values())
        ages = [r.age_days for r in p.reviews if r.age_days is not None]
        p.oldest_loaded_days = max(ages) if ages else None


async def _demo():
    r = MapsReader(headless=True)
    try:
        places = await r.search("Brauerei", 51.2265, 6.7735, 16, limit=4)
        print(len(places), "places")
        done = await asyncio.gather(*(r.place(p, max_reviews=60) for p in places))
        for p in done:
            print(f"{p.name[:34]:34} {p.rating} ({p.count}) removed={p.removed_lo}-{p.removed_hi} "
                  f"reviews={len(p.reviews)} oldest={p.oldest_loaded_days} err={p.error}")
    finally:
        await r.close()


if __name__ == "__main__":
    asyncio.run(_demo())
