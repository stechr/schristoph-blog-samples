"""Prompts for claim extraction and verdict reasoning.

Ported and hardened from the original live-fact-checker. Unlike the original (which fought
Gemini's grounding-vs-JSON-mode limitation with regex fallbacks), here verdicts come back via
Bedrock Converse *structured output* (a tool schema), so the model is constrained to valid JSON.
"""
from __future__ import annotations

from .models import Context

LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French"}


def _lang_name(code: str) -> str:
    return LANG_NAMES.get((code or "").lower(), "the same language as the input")


def extract_prompt(text: str, ctx: Context, max_claims: int) -> str:
    lang = _lang_name(ctx.language)
    return f"""You are a fact-checking analyst. Extract verifiable claims from the text below.

CONTEXT:
{ctx.to_prompt_block()}

TEXT:
\"\"\"
{text}
\"\"\"

RULES:
1. Extract ANY claim containing a number, percentage, date, statistic, named event,
   historical assertion, economic figure, comparison, or attribution — even if approximate
   ("about 60%", "more than 100 years").
2. ALSO extract categorical / universal / absolute factual assertions that have no number —
   e.g. "all X are Y", "X is always/never Z", "X is the largest/first/only ...", "X is Y".
   These are verifiable (often false) and MUST be included.
3. INCLUDE sweeping claims that reference time periods or magnitudes ("100 years of X",
   "the worst in history") — these ARE checkable against historical data.
4. EXCLUDE ONLY: pure opinions/preferences with no factual anchor ("X is the greatest"),
   predictions about the future, greetings, emotional expressions, procedural statements.
5. Return at most {max_claims} claims.
6. If the text has NO factual content at all, return an empty list.
7. Write "summary" as a precise, testable assertion in {lang}.
8. Write "searchQuery" as a specific, <=200-character query to find data that confirms or
   denies the claim.

Return the claims via the provided tool."""


def verdict_prompt(claim: str, summary: str, ctx: Context, evidence_block: str) -> str:
    lang = _lang_name(ctx.language)
    return f"""You are a rigorous fact-checker. Decide whether the claim is TRUE, FALSE, or UNCERTAIN
using ONLY the search evidence provided. Respond in {lang}.

CONTEXT:
{ctx.to_prompt_block()}

CLAIM (testable form): "{summary or claim}"
CLAIM (original): "{claim}"

SEARCH EVIDENCE (snippets with source URLs and publication dates):
{evidence_block}

DECISION RULES:
1. Evidence MATCHES the claim within a reasonable margin (~±10-15%) -> TRUE.
2. Evidence CONTRADICTS the claim (the real figure is substantially different) -> FALSE.
   Example: claim says "60% poverty" but data shows 42% -> FALSE.
3. Sweeping narrative with no single verifiable data point -> UNCERTAIN.
4. No relevant data in the evidence -> UNCERTAIN.
5. Partially true but misleading or missing critical context that changes the meaning -> FALSE.

CALIBRATION (avoid pedantry — judge the claim as a normal reader would):
6. ROUNDING / APPROXIMATION: a rounded or hedged figure that matches the real value within normal
   rounding is TRUE, not FALSE. "Everest is ~8,849 m" vs official 8,848.86 m -> TRUE.
   "about/around/roughly/approximately X" is TRUE if the real value is close to X. Do NOT mark a
   claim FALSE merely because it is rounded or approximate.
7. QUALIFIERS ARE PART OF THE CLAIM: if the claim adds an absolute qualifier — "exactly",
   "always", "never", "regardless of <condition>", "with the naked eye" — you MUST evaluate that
   qualifier. If the base fact is right but the qualifier is wrong, the claim is FALSE.
   Example: "water boils at exactly 100°C regardless of altitude" -> FALSE (altitude changes it).
8. DEFINITIONAL CLAIMS: judge against the standard / scientific definition, not the popular one.
   Example: "the Sahara is the largest desert on Earth" -> FALSE (by definition the largest desert
   is Antarctica, a cold desert).
9. RESERVE UNCERTAIN for facts that are genuinely disputed among reliable sources (e.g. "the
   Amazon is the longest river" — Nile vs Amazon is a real, ongoing dispute) or where the evidence
   truly has no answer. Do NOT use UNCERTAIN for a claim the evidence lets you confirm or refute.

ABSOLUTE RULES:
- ALWAYS state "Claim says [X]. Evidence shows [Y]." in the explanation.
- The explanation MUST be consistent with the verdict. If the evidence shows a different figure,
  the verdict MUST be FALSE — never TRUE.
- Keep the explanation to 2-3 sentences, in {lang}.
- Base confidence on the strength and agreement of the evidence (0.0-1.0).

Return your decision via the provided tool."""


# --- Structured-output tool schemas (Bedrock Converse toolConfig) -----------

EXTRACT_TOOL = {
    "toolSpec": {
        "name": "return_claims",
        "description": "Return the list of verifiable claims extracted from the text.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim": {"type": "string", "description": "verbatim quote"},
                            "summary": {"type": "string", "description": "testable assertion"},
                            "searchQuery": {"type": "string", "description": "<=200 char query"},
                        },
                        "required": ["claim", "summary", "searchQuery"],
                    },
                }
            },
            "required": ["claims"],
        }},
    }
}

VERDICT_TOOL = {
    "toolSpec": {
        "name": "return_verdict",
        "description": "Return the fact-check verdict for the claim.",
        "inputSchema": {"json": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["TRUE", "FALSE", "UNCERTAIN"]},
                "confidence": {"type": "number", "description": "0.0 to 1.0"},
                "explanation": {"type": "string"},
                "claimNormalized": {"type": "string"},
            },
            "required": ["verdict", "confidence", "explanation"],
        }},
    }
}
