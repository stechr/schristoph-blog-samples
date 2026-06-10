# Speaker notes — Sample Task Board walkthrough

A human-readable companion to [`sample-content/narration.json`](../sample-content/narration.json).
This is the *hand-made* sample script the pipeline ships with. Times are approximate
(Amazon Polly Matthew, neural); the pipeline measures the real audio length per segment and
holds each on-screen scene for exactly that long, so the numbers below are a guide.

The video opens with a short **3-second blank lead-in** (breathing room before the
walkthrough begins), then plays the seven segments, then a 1-second tail.

| # | On screen | Voiceover |
|---|-----------|-----------|
| 1 | Board loaded, nothing moving | Intro — what Sample Task Board is, the stats row + today's board. |
| 2 | Stats row | The four live counters: total, open, done, completion rate. |
| 3 | Type "Prepare release notes" → Enter | Add a task; it lands on top, tagged high priority. |
| 4 | Stats row updates | Counters reacted: total ↑, open ↑, completion adjusted — no refresh. |
| 5 | Two tasks toggle to done | Close out work; activity feed logs each; completion climbs. |
| 6 | Filter Open → Done → All | Filters keep you focused; switch between planning and review. |
| 7 | Final board state | Takeaway — one honest board with live numbers and an activity trail. |

## How this maps to the recorder

Each table row is one `segment` in `narration.json`. The `steps` array drives the app:

- **type** → types into the new-task input and presses Enter
- **eval** → calls a `window.__demo` helper (e.g. `toggle(1)` to complete task 1)
- **click** → clicks an element by its `data-testid` (the filter buttons)
- **wait / pause** → holds the current screen

To script your own content, run `make script-from-app` (or `make script-from-spec
SPEC=…`) and edit the draft — then point `--script` at it.
