#!/usr/bin/env python3
"""Propose a narration script from a product spec OR a web app's source code.

This answers "how do I make a script for my OWN content?" two ways:

  1. A stdlib-only HEURISTIC draft you can edit by hand (no network, no deps), and
  2. A ready-to-paste LLM PROMPT (and an optional --bedrock call) that turns the same
     extracted facts into a polished, segment-by-segment narration.

Usage:
  # From the sample app's source:
  python scripts/generate_script.py --app sample-app --out /tmp/draft.json \
      --prompt-out /tmp/prompt.txt
  # From a product spec (markdown/plain text):
  python scripts/generate_script.py --spec my-product.md --out /tmp/draft.json
  # Optionally let Amazon Bedrock write the polished script from the prompt:
  python scripts/generate_script.py --app sample-app --bedrock \
      --model anthropic.claude-3-5-sonnet-20240620-v1:0 --out /tmp/script.json

The draft is a valid narration.json (see sample-content/narration.json). Always review
and tighten the wording — a generator gives you a scaffold, not a final cut.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


# ---------- extraction ----------------------------------------------------------------
class _AppParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.headings: list[str] = []
        self.buttons: list[dict] = []   # {"testid":..., "label":...}
        self.inputs: list[dict] = []
        self._cap = None
        self._cur_testid = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("title", "h1", "h2", "h3"):
            self._cap = tag
        if tag == "button":
            self._cur_testid = a.get("data-testid")
            self._cap = "button"
        if tag == "input":
            self.inputs.append({"testid": a.get("data-testid"),
                                "placeholder": a.get("placeholder", "")})

    def handle_endtag(self, tag):
        if tag == self._cap or (tag == "button" and self._cap == "button"):
            self._cap = None
            self._cur_testid = None

    def handle_data(self, data):
        text = data.strip()
        if not text or not self._cap:
            return
        if self._cap == "title":
            self.title = text
        elif self._cap in ("h1", "h2", "h3"):
            self.headings.append(text)
        elif self._cap == "button" and self._cur_testid:
            self.buttons.append({"testid": self._cur_testid, "label": text})


def extract_from_app(app_dir: Path) -> dict:
    index = app_dir / "index.html"
    if not index.exists():
        sys.exit(f"[gen] no index.html in {app_dir}")
    p = _AppParser()
    p.feed(index.read_text())
    return {"title": p.title or app_dir.name, "headings": p.headings,
            "buttons": p.buttons, "inputs": p.inputs}


def extract_from_spec(spec_file: Path) -> dict:
    text = spec_file.read_text()
    title = ""
    sections: list[str] = []
    for line in text.splitlines():
        m1 = re.match(r"#\s+(.*)", line)
        m2 = re.match(r"##\s+(.*)", line)
        if m1 and not title:
            title = m1.group(1).strip()
        elif m2:
            sections.append(m2.group(1).strip())
    return {"title": title or spec_file.stem, "headings": sections,
            "buttons": [], "inputs": []}


# ---------- heuristic draft ------------------------------------------------------------
def heuristic_script(facts: dict) -> dict:
    title = facts["title"]
    segs: list[dict] = []
    segs.append({"id": "seg1",
                 "text": f"This is {title}. Here's a quick walkthrough of what it does "
                         f"and how it works.",
                 "steps": [{"action": "wait"}]})
    for h in facts.get("headings", [])[:2]:
        segs.append({"id": f"seg{len(segs)+1}",
                     "text": f"{h}. (Describe what this area shows and why it matters.)",
                     "steps": [{"action": "wait"}]})
    for inp in facts.get("inputs", [])[:1]:
        if inp.get("testid"):
            segs.append({"id": f"seg{len(segs)+1}",
                         "text": "Let's add something. (Describe the input and the result.)",
                         "steps": [{"action": "type", "testid": inp["testid"],
                                    "text": "Example entry", "submit": True}]})
    for btn in facts.get("buttons", [])[:3]:
        if btn.get("testid"):
            segs.append({"id": f"seg{len(segs)+1}",
                         "text": f"Here I use “{btn['label']}”. (Describe what changes.)",
                         "steps": [{"action": "click", "testid": btn["testid"]}]})
    segs.append({"id": f"seg{len(segs)+1}",
                 "text": "That's the core idea. (Close with the one takeaway you want "
                         "viewers to remember.)",
                 "steps": [{"action": "wait"}]})
    return {"title": f"{title} — walkthrough",
            "app": {"entry": "sample-app/index.html", "width": 1280, "height": 720, "fps": 25},
            "lead_in_seconds": 3.0, "tail_seconds": 1.0, "segments": segs}


# ---------- LLM prompt -----------------------------------------------------------------
PROMPT_TMPL = """\
You are scripting a short product-demo voiceover. Produce a narration script as JSON
matching this schema (no prose, JSON only):

{{
  "title": str,
  "app": {{"entry": "sample-app/index.html", "width": 1280, "height": 720, "fps": 25}},
  "lead_in_seconds": 3.0,
  "tail_seconds": 1.0,
  "segments": [
    {{"id": "seg1", "text": "<one or two spoken sentences>",
      "steps": [{{"action": "wait"}}]}}
  ]
}}

Step actions you may use inside a segment's "steps":
  {{"action": "wait"}}
  {{"action": "pause", "seconds": 1.5}}
  {{"action": "click", "testid": "<data-testid>"}}
  {{"action": "type",  "testid": "<data-testid>", "text": "...", "submit": true}}
  {{"action": "eval",  "call": "<window.__demo helper>", "args": [...]}}

Rules: 5-8 segments; conversational, spoken English (no bullet lists); each segment's
text should take roughly 6-12 seconds to read; the on-screen steps must match what the
narration describes; open with context and close with one takeaway.

Product/app facts to script from:
TITLE: {title}
HEADINGS/SECTIONS: {headings}
BUTTONS (clickable, with data-testid): {buttons}
INPUTS (with data-testid): {inputs}
"""


def build_prompt(facts: dict) -> str:
    return PROMPT_TMPL.format(
        title=facts["title"],
        headings=", ".join(facts.get("headings", [])) or "(none)",
        buttons=", ".join(f"{b['label']}[{b['testid']}]" for b in facts.get("buttons", []) if b.get("testid")) or "(none)",
        inputs=", ".join(f"{i.get('placeholder','input')}[{i['testid']}]" for i in facts.get("inputs", []) if i.get("testid")) or "(none)",
    )


def via_bedrock(prompt: str, model: str, region: str) -> dict:
    import boto3

    br = boto3.client("bedrock-runtime", region_name=region)
    resp = br.converse(
        modelId=model,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 2000, "temperature": 0.4},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    m = re.search(r"\{.*\}", text, re.S)   # tolerate fences/prose around the JSON
    if not m:
        sys.exit("[gen] Bedrock returned no JSON object")
    return json.loads(m.group(0))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--app", help="path to a web app dir containing index.html")
    src.add_argument("--spec", help="path to a product spec (markdown/plain text)")
    ap.add_argument("--out", default="/tmp/narration-draft.json")
    ap.add_argument("--prompt-out", default=None, help="also write the LLM prompt here")
    ap.add_argument("--bedrock", action="store_true",
                    help="call Amazon Bedrock to write the polished script from the prompt")
    ap.add_argument("--model", default="anthropic.claude-3-5-sonnet-20240620-v1:0")
    ap.add_argument("--region", default="us-east-1")
    a = ap.parse_args()

    facts = extract_from_app(Path(a.app)) if a.app else extract_from_spec(Path(a.spec))
    prompt = build_prompt(facts)
    if a.prompt_out:
        Path(a.prompt_out).write_text(prompt)
        print(f"[gen] wrote LLM prompt -> {a.prompt_out}")

    if a.bedrock:
        try:
            script = via_bedrock(prompt, a.model, a.region)
            print(f"[gen] Bedrock ({a.model}) produced a script")
        except Exception as e:  # noqa: BLE001
            print(f"[gen] Bedrock unavailable ({e}); falling back to heuristic draft")
            script = heuristic_script(facts)
    else:
        script = heuristic_script(facts)

    Path(a.out).write_text(json.dumps(script, indent=2))
    print(f"[gen] wrote narration draft -> {a.out}  ({len(script['segments'])} segments)")
    print("[gen] Review & tighten the wording before recording.")


if __name__ == "__main__":
    main()
