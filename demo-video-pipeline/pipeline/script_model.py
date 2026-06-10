"""Load and validate a narration script (the JSON in sample-content/narration.json).

A script describes the video dimensions, an optional blank lead-in (breathing room
before the walkthrough begins), and an ordered list of narration segments. Each segment
carries the voiceover text plus the on-screen *steps* the recorder performs while that
line plays.

Step kinds (all optional per segment; an empty/`wait` step just holds the screen):
  {"action": "wait"}                                  hold the current screen
  {"action": "pause",  "seconds": 1.5}                explicit hold (inside a step list)
  {"action": "click",  "testid": "filter-open"}       click element by data-testid
  {"action": "type",   "testid": "new-task-input",    type into an input,
                        "text": "...", "submit": true}  optionally pressing Enter
  {"action": "eval",   "call": "toggle", "args": [1]} call a window.__demo helper
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Segment:
    id: str
    text: str
    steps: list[dict[str, Any]] = field(default_factory=lambda: [{"action": "wait"}])


@dataclass
class Script:
    title: str
    entry: str                      # path to the app's index.html, relative to repo root
    width: int
    height: int
    fps: int
    lead_in_seconds: float
    tail_seconds: float
    segments: list[Segment]

    @property
    def texts(self) -> list[str]:
        return [s.text for s in self.segments]


def load_script(path: str | Path) -> Script:
    data = json.loads(Path(path).read_text())
    app = data.get("app", {})
    segs = [
        Segment(id=s["id"], text=s["text"],
                steps=s.get("steps") or [{"action": "wait"}])
        for s in data["segments"]
    ]
    if not segs:
        raise ValueError(f"{path}: script has no segments")
    return Script(
        title=data.get("title", "demo"),
        entry=app.get("entry", "sample-app/index.html"),
        width=int(app.get("width", 1280)),
        height=int(app.get("height", 720)),
        fps=int(app.get("fps", 25)),
        lead_in_seconds=float(data.get("lead_in_seconds", 0.0)),
        tail_seconds=float(data.get("tail_seconds", 0.0)),
        segments=segs,
    )
