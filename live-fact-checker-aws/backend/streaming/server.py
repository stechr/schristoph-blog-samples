"""Local live-streaming fact-check server (PoC — Shape A from the design note §11).

Browser mic (16 kHz PCM16) --WebSocket--> this server:
  * feeds audio to Amazon Transcribe Streaming,
  * streams partial/final transcript back to the browser,
  * on each finalized segment, extracts claims (rolling window + dedup) and fans out
    verification concurrently (bounded), streaming claim.identified / claim.verified events.

Reuses the exact same `factchecker` primitives as the REST backend — only the *front* changes
(stream of claims instead of one request). Runs locally with your default AWS credentials;
productionizing = containerize this to Fargate / AgentCore Runtime.

Run:
    cd backend
    uv run --with amazon-transcribe --with websockets python streaming/server.py
    # serves ws://localhost:8765
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

# Make the `factchecker` package importable (src layout).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from amazon_transcribe.client import TranscribeStreamingClient  # noqa: E402
from amazon_transcribe.model import TranscriptEvent  # noqa: E402
import websockets  # noqa: E402

from factchecker import config, grounding, bedrock  # noqa: E402
from factchecker.models import Context, Verdict  # noqa: E402

REGION = config.AWS_REGION
WS_HOST = os.environ.get("WS_HOST", "localhost")
WS_PORT = int(os.environ.get("WS_PORT", "8765"))
MAX_CONCURRENT = int(os.environ.get("LIVE_MAX_CONCURRENT", "4"))
SESSION_QUERY_BUDGET = int(os.environ.get("LIVE_QUERY_BUDGET", "50"))  # cap web-search spend/session
EXTRACT_WINDOW_WORDS = int(os.environ.get("LIVE_EXTRACT_WINDOW", "20"))  # accumulate this many finalized words before extracting


async def _send(ws, obj):
    try:
        await ws.send(json.dumps(obj))
    except websockets.ConnectionClosed:
        pass


class Session:
    """Per-connection state: rolling dedup + bounded verification fan-out + query budget."""

    def __init__(self, ws):
        self.ws = ws
        self.seen: set[str] = set()
        self.sem = asyncio.Semaphore(MAX_CONCURRENT)
        self.tasks: set[asyncio.Task] = set()
        self.queries_used = 0
        self.ctx = Context(language="en")
        self.pending = ""   # finalized text not yet sent to extraction

    async def feed_final(self, text: str):
        """Accumulate finalized transcript; extract once a rolling window has built up."""
        self.pending = (self.pending + " " + text).strip()
        if len(self.pending.split()) >= EXTRACT_WINDOW_WORDS:
            window, self.pending = self.pending, ""
            await self._extract(window)

    async def flush(self):
        """Extract whatever finalized text remains (called when the stream ends)."""
        if self.pending.strip():
            window, self.pending = self.pending, ""
            await self._extract(window)

    async def _extract(self, text: str):
        try:
            claims = await asyncio.to_thread(bedrock.extract_claims, text, self.ctx, config.MAX_CLAIMS_PER_EXTRACT)
        except Exception as exc:  # noqa: BLE001
            await _send(self.ws, {"type": "status", "message": f"extract error: {exc}"[:160]})
            return
        for c in claims:
            key = " ".join((c.claim or "").lower().split())
            if not key or key in self.seen:
                continue
            self.seen.add(key)
            if self.queries_used >= SESSION_QUERY_BUDGET:
                await _send(self.ws, {"type": "status", "message": "session query budget reached"})
                return
            self.queries_used += 1
            cid = "c-" + uuid.uuid4().hex[:8]
            await _send(self.ws, {"type": "claim.identified", "id": cid, "claim": c.claim})
            t = asyncio.create_task(self._verify(cid, c))
            self.tasks.add(t)
            t.add_done_callback(self.tasks.discard)

    async def _verify(self, cid: str, claim):
        async with self.sem:
            try:
                sources = await asyncio.to_thread(grounding.web_search, claim.summary or claim.claim, None)
                data = await asyncio.to_thread(
                    bedrock.reason_verdict, claim.claim, claim.summary, self.ctx, grounding.evidence_block(sources)
                )
                verdict = str(data.get("verdict", "UNCERTAIN")).upper()
                await _send(self.ws, {
                    "type": "claim.verified", "id": cid, "verdict": verdict,
                    "confidence": data.get("confidence", 0), "explanation": data.get("explanation", ""),
                    "sources": [s.to_json() for s in sources],
                })
            except Exception as exc:  # noqa: BLE001
                await _send(self.ws, {
                    "type": "claim.verified", "id": cid, "verdict": "UNCERTAIN",
                    "confidence": 0, "explanation": f"Error: {exc}"[:160], "sources": [],
                })


async def handle(ws):
    session = Session(ws)
    client = TranscribeStreamingClient(region=REGION)
    stream = await client.start_stream_transcription(
        language_code="en-US", media_sample_rate_hz=16000, media_encoding="pcm",
    )
    await _send(ws, {"type": "status", "message": "listening"})

    async def pump_audio():
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    await stream.input_stream.send_audio_event(audio_chunk=msg)
                elif msg == "stop":
                    break
        finally:
            await stream.input_stream.end_stream()

    async def pump_transcripts():
        async for event in stream.output_stream:
            if not isinstance(event, TranscriptEvent):
                continue
            for result in event.transcript.results:
                if not result.alternatives:
                    continue
                text = result.alternatives[0].transcript
                await _send(ws, {"type": "transcript", "text": text, "partial": result.is_partial})
                if not result.is_partial:
                    await session.feed_final(text)

    await asyncio.gather(pump_audio(), pump_transcripts())
    await session.flush()
    if session.tasks:
        await asyncio.gather(*session.tasks, return_exceptions=True)


async def main():
    print(f"live fact-check server on ws://{WS_HOST}:{WS_PORT}  (region {REGION}, "
          f"grounding {config.GROUNDING_PROVIDER})")
    async with websockets.serve(handle, WS_HOST, WS_PORT, max_size=2 ** 22):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
