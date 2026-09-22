---
name: personal-brand-canvas
description: Interactively elicit someone's personal brand through probing, specific questions — one block at a time — and synthesize a filled Personal Brand Canvas (positioning statement, tagline, content pillars, next actions). Use when the user says "personal brand canvas", "build my personal brand", "brand canvas", "define my brand", "personal branding", "brand positioning", or wants to run themselves (or a sample persona) through a guided branding interview.
---

# Personal Brand Canvas

## Overview

A guided, conversational interview that turns scattered self-knowledge into a one-page **Personal Brand Canvas** — the person-scale analog of the Business Model Canvas. The agent interviews the subject **block by block**, **probes for specificity**, reflects each block back for confirmation, then synthesizes a positioning statement, a tagline, content pillars, and concrete next actions.

Two modes:

- **live** — interview the real user, in conversation, in their own words.
- **showcase** — run the interview against a provided sample persona (the agent generates plausible, in-voice answers) to produce a demo canvas for a talk, workshop, or blog post.

## The Canvas — 9 blocks → 4 synthesized outputs

| # | Block | Elicits |
|---|-------|---------|
| 1 | Purpose & Values | why you do this; 3 non-negotiable values |
| 2 | Vision & Goals | 12-month + 3-year direction; the change you want to create |
| 3 | Audience | who you serve/reach — specifically; and who it is *not* for |
| 4 | Unique Value | your "only-ness" — the intersection few others occupy |
| 5 | Strengths & Superpowers | what people repeatedly come to you for |
| 6 | Passions & Interests | what energizes you; where your emotional fuel is |
| 7 | Story & Proof | the narrative arc + credibility/evidence |
| 8 | Personality & Voice | 3–5 adjectives; tone; how you show up |
| 9 | Channels & Content Pillars | where you show up + 3–4 recurring themes you'll own |

**Synthesized from the blocks:** a **positioning statement** ("I help *[audience]* to *[outcome]* by *[unique approach]*, because *[purpose]*"), 2–3 **tagline** options, **3–4 content pillars** (each with example post angles), and **3 next actions**.

See `references/canvas-template.md` for the full canvas structure and `references/question-bank.md` for the per-block probing questions and follow-up ladders, and `references/block-guidance.md` for **what a strong entry looks like per block** (the specific / complete / distinctive bar + weak→strong examples).

## Parameters

- **mode** (required): `live` or `showcase`
- **subject** (optional): in `showcase`, the persona description; in `live`, defaults to the current user
- **output_path** (optional): where to write the filled canvas (defaults below)

## Workflow

### 1. Frame the session

Set expectations before asking anything.

**Constraints:**
- You MUST briefly explain the canvas and that it runs as a short block-by-block interview (~20–30 min), and that answers can be revisited.
- You MUST NOT lecture or dump the whole framework at once, because a wall of theory kills the conversational momentum the interview depends on.
- You SHOULD tell the subject there are no wrong answers and they can say "skip" or "come back to it".

### 2. Interview block by block

Walk the 9 blocks in order. For each: ask the lead question, probe, reflect back, confirm, move on.

**Constraints:**
- You MUST ask about **ONE block at a time**, not present all questions at once, because a long questionnaire overwhelms and produces shallow answers.
- You MUST **push past generic answers with a targeted follow-up** (e.g. "'I help people' — help *whom*, to do *what*, that they couldn't before?"), because specificity is the entire value of the canvas.
- You MUST hold every recorded entry to the **specific / complete / distinctive** bar in `references/block-guidance.md`: if an entry could be copied onto someone else's canvas it is too weak — probe again, because a generic canvas is worthless.
- You MUST challenge **inflated or unsupported** claims, not only vague ones: when Unique Value or Strengths asserts something ("X is rare", "I'm the best at Y"), ask for the evidence and confirm it traces to a proof in Story & Proof — an unbacked claim is not earned, because a canvas full of self-flattery is as useless as a generic one.
- You MUST **reflect each block back** as a crisp 1–2 line summary and get a yes/adjust before advancing, because it keeps the canvas the subject's own and catches drift early.
- You MUST **preserve the subject's own words and voice** and MUST NOT substitute your phrasing for theirs, because it is their brand, not yours.
- You MAY let the subject defer a block they can't answer yet; if so, you MUST flag it as `[to revisit]` in the canvas rather than inventing an answer.
- You SHOULD use `references/question-bank.md` for lead questions and follow-up ladders, adapting wording to the subject.

### 3. Synthesize

Draft the four synthesized outputs strictly from the collected blocks.

**Constraints:**
- You MUST derive the positioning statement, tagline, pillars, and actions **only from the subject's answers**, and MUST NOT introduce facts, achievements, or claims the subject did not give, because fabricated brand claims carry the subject's name.
- You MUST render the positioning statement in the "I help *[audience]* to *[outcome]* by *[approach]*, because *[purpose]*" shape.
- You MUST offer **2–3 tagline options** rather than a single take, so the subject chooses.
- You SHOULD make each content pillar concrete with 2–3 example post/talk angles drawn from blocks 6 and 9.

### 4. Produce the filled canvas artifact

Write the completed canvas to a file using the template.

**Location (default):**
- Save the filled canvas as `{yyyy-mm-dd}-{firstname}-brand-canvas.md`.
- Keep any shareable / sample canvas in an `examples/` folder as `{persona-slug}-brand-canvas.md`.

**Constraints:**
- You MUST use the structure in `references/canvas-template.md` and include all 9 blocks + the 4 synthesized outputs.
- You MUST clearly label a showcase/sample canvas as a **fictional persona** at the top, because it will be shared publicly and must not be mistaken for a real person.
- You SHOULD open the finished canvas for the subject to review.

### 5. (Optional) Share / export

Stage the skill and/or a sample canvas for sharing.

**Constraints:**
- You MUST scan for secrets and personal data (paths, aliases, account IDs, emails) before staging anything to a public or shared repo, because they must never leak.
- You MUST use a clearly fictional name for any shared sample persona.
- You SHOULD keep this skill copy self-contained (no personal paths) so it stands alone.

## Showcase mode (talks / demos / blog posts)

To demonstrate the skill without a live subject: take the persona from `subject`, then **run the full block-by-block interview as a scripted dialogue** — the agent voices both the probing questions and the persona's plausible, specific answers — and produce the filled canvas. This makes a compelling "watch the interview, see the output" artifact for a talk. Keep the persona and every detail fictional and labelled as such.
