"""Ghost Stars — local web server.

    uv run --with playwright python server.py      # then open http://localhost:8765

Endpoints
  GET /                      the single-page UI (static/index.html)
  GET /api/region?q=...      region outline + bbox via OpenStreetMap Nominatim
  GET /api/scan?...          Server-Sent Events: places found, then one event per analysed place
       q=<region>  cat=<category>  limit=<n>  assumed=<1..3>  fresh=0|1
Data is cached per place for 24 h in cache/places.json (local only, never published).
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

from maps_reader import MapsReader, Place, Review
import metrics

ROOT = Path(__file__).parent
STATIC = ROOT / "static"
CACHE_FILE = ROOT / "cache" / "places.json"
CACHE_TTL = 24 * 3600
PORT = int(os.environ.get("PORT", "8765"))
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA_NOMINATIM = "ghost-stars/0.1 (local proof of concept)"
MAX_LIMIT = 40

_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True).start()
_reader = MapsReader(headless=os.environ.get("HEADED") != "1", parallel=int(os.environ.get("PARALLEL", "3")))
_cache_lock = threading.Lock()


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except Exception:
        return {}


_cache = _load_cache()


def _save_cache():
    CACHE_FILE.parent.mkdir(exist_ok=True)
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_cache, ensure_ascii=False))
    tmp.replace(CACHE_FILE)


def _key(url: str) -> str:
    return url.split("?")[0].split("/data=")[-1] or url


def nominatim(q: str) -> dict | None:
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "polygon_geojson": 1, "polygon_threshold": 0.0005, "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": UA_NOMINATIM, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.loads(r.read())
    if not res:
        return None
    hit = res[0]
    s, n, w, e = map(float, hit["boundingbox"])
    return {"name": hit.get("display_name"), "lat": float(hit["lat"]), "lng": float(hit["lon"]),
            "bbox": [s, w, n, e], "geojson": hit.get("geojson")}


def zoom_for(bbox: list[float]) -> int:
    s, w, n, e = bbox
    span = max(n - s, (e - w) * 0.62)
    for z, lim in [(17, 0.006), (16, 0.012), (15, 0.025), (14, 0.05), (13, 0.1), (12, 0.2), (11, 0.4)]:
        if span <= lim:
            return z
    return 10


def _place_from_cache(d: dict) -> Place:
    p = Place(**{k: v for k, v in d.items() if k not in ("reviews", "histogram")})
    p.histogram = {int(k): v for k, v in (d.get("histogram") or {}).items()}
    p.reviews = [Review(**r) for r in d.get("reviews") or []]
    return p


def _inside(p: Place, region: dict) -> bool:
    if p.lat is None or not region:
        return True
    s, w, n, e = region["bbox"]
    pad = 0.002
    return s - pad <= p.lat <= n + pad and w - pad <= p.lng <= e + pad


class Handler(BaseHTTPRequestHandler):
    server_version = "GhostStars/0.1"

    def log_message(self, fmt, *args):
        print(time.strftime("%H:%M:%S"), self.address_string(), fmt % args)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            name = u.path.removeprefix("/static/")
            ctype = {"js": "text/javascript", "css": "text/css"}.get(name.rsplit(".", 1)[-1], "application/octet-stream")
            return self._static(name, ctype)
        if u.path == "/api/region":
            try:
                r = nominatim(qs.get("q", ""))
            except Exception as e:
                return self._json({"error": f"Nominatim: {e}"}, 502)
            return self._json(r or {"error": "Area not found"}, 200 if r else 404)
        if u.path == "/api/scan":
            return self._scan(qs)
        self.send_error(404)

    def _static(self, name: str, ctype: str):
        f = (STATIC / name).resolve()
        if STATIC.resolve() not in f.parents or not f.is_file():
            return self.send_error(404)
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _event(self, kind: str, data) -> bool:
        try:
            self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def _scan(self, qs: dict):
        region_q = qs.get("q", "").strip()
        cat = qs.get("cat", "Restaurant").strip()
        limit = max(1, min(int(qs.get("limit", "15")), MAX_LIMIT))
        assumed = float(qs.get("assumed", "1"))
        fresh = qs.get("fresh") == "1"
        if not region_q:
            return self._json({"error": "Missing area"}, 400)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            region = nominatim(region_q)
        except Exception as e:
            self._event("fail", {"error": f"Nominatim: {e}"})
            return
        if not region:
            self._event("fail", {"error": f"Area '{region_q}' not found"})
            return
        self._event("region", region)

        query = f"{cat} {region_q}"
        fut = asyncio.run_coroutine_threadsafe(
            _reader.search(query, region["lat"], region["lng"], zoom_for(region["bbox"]), limit=limit * 2), _loop)
        try:
            found = fut.result(timeout=120)
        except Exception as e:
            self._event("fail", {"error": f"Google Maps search failed: {e}"})
            return
        inside = [p for p in found if _inside(p, region)][:limit]
        if not self._event("places", {"query": query, "found": len(found),
                                      "places": [{"name": p.name, "lat": p.lat, "lng": p.lng, "url": p.url}
                                                 for p in inside]}):
            return

        todo, done = [], []
        with _cache_lock:
            for p in inside:
                c = _cache.get(_key(p.url))
                if c and not fresh and time.time() - c.get("fetched_at", 0) < CACHE_TTL and not c.get("error"):
                    done.append(_place_from_cache(c))
                else:
                    todo.append(p)
        for p in done:
            if not self._event("place", self._row(p, assumed, cached=True)):
                return

        futs = [asyncio.run_coroutine_threadsafe(_reader.place(p), _loop) for p in todo]
        for f in futs:
            try:
                p = f.result(timeout=240)
            except Exception as e:
                self._event("place_error", {"error": str(e)})
                continue
            with _cache_lock:
                _cache[_key(p.url)] = p.to_json()
                _save_cache()
            if not self._event("place", self._row(p, assumed, cached=False)):
                for g in futs:
                    g.cancel()
                return
        self._event("done", {"n": len(inside)})

    @staticmethod
    def _row(p: Place, assumed: float, cached: bool) -> dict:
        d = p.to_json()
        return {"name": p.name, "url": p.url, "lat": p.lat, "lng": p.lng, "category": p.category,
                "error": p.error, "cached": cached, "fetched_at": p.fetched_at,
                "histogram": d["histogram"],
                "metrics": metrics.summarize(d, assumed=assumed)}


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Ghost Stars → http://localhost:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run_coroutine_threadsafe(_reader.close(), _loop).result(timeout=20)


if __name__ == "__main__":
    main()
