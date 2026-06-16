"""
Take store — a tiny JSON-backed index of recorded takes and their scorecards.

Kept deliberately simple (a single index.json under the recordings dir) so it is
trivially inspectable and needs no DB dependency. Each take entry stores the
master wav path, scorecard dict, verdict, user keep/reject flag, an editable
friendly name, a human-readable created timestamp, and a content hash used to
de-duplicate accidental double-inserts of the same recording.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path


def default_recordings_dir() -> Path:
    """Resolve the recordings dir from env or a sensible default (no hardcoded user)."""
    env = os.environ.get("VOICE_STUDIO_RECORDINGS")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".voice-sample-studio" / "recordings"


def sha1_of_file(path: str | Path) -> str:
    """Content hash of a file (used to dedupe identical recordings)."""
    h = hashlib.sha1(usedforsecurity=False)  # dedup/content hash only, not security
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def sanitize_name(name: str, fallback: str = "take") -> str:
    """Filesystem-safe slug from a friendly take name."""
    slug = re.sub(r"[^\w\-]+", "_", (name or "").strip()).strip("_")
    return slug[:48] or fallback


def fmt_local(ts: float) -> str:
    """Human-readable local timestamp: YYYY-MM-DD HH:MM:SS."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


@dataclass
class Take:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    name: str = ""                  # editable friendly name
    master_wav: str = ""
    source_sha1: str = ""           # content hash (dedupe guard)
    scorecard: dict = field(default_factory=dict)
    verdict: str = "reject"
    overall_score: float = 0.0
    stars: int = 1
    kept: bool | None = None        # user decision; None = undecided
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def created_str(self) -> str:
        return fmt_local(self.created)


class TakeStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser() if root else default_recordings_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.takes: list[Take] = []
        self.load()

    def load(self):
        if self.index_path.exists():
            try:
                data = json.loads(self.index_path.read_text())
                # tolerate older index entries missing the new fields
                known = set(Take.__dataclass_fields__.keys())
                self.takes = [Take(**{k: v for k, v in t.items() if k in known})
                              for t in data.get("takes", [])]
            except Exception:
                self.takes = []
        return self.takes

    def save(self):
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"takes": [t.to_dict() for t in self.takes]}, indent=2))
        tmp.replace(self.index_path)

    def add(self, master_wav: str, scorecard: dict, name: str = "",
            source_sha1: str | None = None) -> Take:
        """
        Add a take. Idempotent: if a take with the same content hash already
        exists, return that existing take instead of inserting a duplicate (this
        guards against the Gradio audio component firing the handler twice on the
        first mic-stop). A redundant master file is removed to avoid orphans.
        """
        sha1 = source_sha1 if source_sha1 is not None else sha1_of_file(master_wav)
        if sha1:
            existing = next((t for t in self.takes if t.source_sha1 == sha1), None)
            if existing is not None:
                # drop the redundant copy if it is a distinct file
                if master_wav and Path(master_wav) != Path(existing.master_wav):
                    try:
                        p = Path(master_wav)
                        if p.exists():
                            p.unlink()
                    except OSError:
                        pass
                return existing
        take = Take(
            name=name or "",
            master_wav=master_wav,
            source_sha1=sha1,
            scorecard=scorecard,
            verdict=scorecard.get("verdict", "reject"),
            overall_score=scorecard.get("overall_score", 0.0),
            stars=int(scorecard.get("stars", 1)),
        )
        self.takes.append(take)
        self.save()
        return take

    def get(self, take_id: str) -> Take | None:
        return next((t for t in self.takes if t.id == take_id), None)

    def set_kept(self, take_id: str, kept: bool):
        t = self.get(take_id)
        if t:
            t.kept = kept
            self.save()
        return t

    def set_name(self, take_id: str, name: str):
        t = self.get(take_id)
        if t:
            t.name = (name or "").strip()
            self.save()
        return t

    def delete(self, take_id: str, remove_file: bool = True) -> bool:
        t = self.get(take_id)
        if not t:
            return False
        if remove_file and t.master_wav and Path(t.master_wav).exists():
            try:
                Path(t.master_wav).unlink()
            except OSError:
                pass
        self.takes = [x for x in self.takes if x.id != take_id]
        self.save()
        return True

    def sorted_takes(self) -> list[Take]:
        """Takes newest-first — the canonical order used by both as_rows() and
        the master-detail row-select handler (so a selected row index maps back
        to the right take)."""
        return sorted(self.takes, key=lambda x: x.created, reverse=True)

    def take_at_row(self, row: int) -> Take | None:
        """Map a Dataframe row index (newest-first order) to its Take."""
        rows = self.sorted_takes()
        if row is None or row < 0 or row >= len(rows):
            return None
        return rows[row]

    # Clean, non-cramped column labels for the single-page master list.
    # (Detailed metrics — sample rate, dynamics, pauses, transcript — live in the
    # detail panel, not this overview table.)
    COLUMNS = ["Time", "Name", "ID", "Duration", "SNR (dB)", "Pace (WPM)",
               "Pitch var (st)", "MOS", "Score", "Stars", "Verdict", "Kept"]

    def as_rows(self) -> list[list]:
        rows = []
        for t in self.sorted_takes():
            sc = t.scorecard
            wpm = sc.get("wpm")
            pstd = sc.get("pitch_std_semitones")
            mos = sc.get("mos")
            rows.append([
                t.created_str,
                t.name or "—",
                t.id,
                f"{sc.get('duration', 0):.1f} s",
                f"{sc.get('snr_db', 0):.1f}",
                f"{wpm:.0f}" if wpm is not None else "n/a",
                f"{pstd:.1f}" if pstd is not None else "n/a",
                f"{mos:.2f}" if mos is not None else "n/a",
                f"{t.overall_score:.0f}",
                "★" * int(t.stars) + "☆" * (5 - int(t.stars)),
                t.verdict,
                "✓" if t.kept else ("✗" if t.kept is False else "—"),
            ])
        return rows
