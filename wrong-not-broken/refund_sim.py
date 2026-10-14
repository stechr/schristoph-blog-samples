"""Wrong, not broken: one refund run, three evaluators.

An offline simulation. There is no model call and no AWS call. A stub
"agent" answers from whatever policy document retrieval hands it, and the
retrieval index still points at last quarter's version. The run is traced
with the OpenTelemetry SDK, then three local checks score the trace:

  context_check    - is the answer supported by the retrieved document?
  reference_check  - does the answer match the expected answer?
  freshness_check  - was the retrieved document the current version?
"""
import json
import re
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

# Two versions of the same policy. Only one is current.
POLICY_DOCS = {
    "refund-policy@2026-Q2": "Damaged-in-transit items: refund of $40 plus return shipping.",
    "refund-policy@2026-Q3": "Damaged-in-transit items: refund of $140 plus return shipping.",
}
CURRENT_VERSION = "refund-policy@2026-Q3"   # the source of truth
STALE_INDEX = "refund-policy@2026-Q2"       # what retrieval still returns

exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("refund-agent-sim")


def retrieve(question: str) -> tuple[str, str]:
    with tracer.start_as_current_span("retrieve_policy") as span:
        doc_id = STALE_INDEX
        span.set_attribute("retrieval.document.id", doc_id.split("@")[0])
        span.set_attribute("retrieval.document.version", doc_id.split("@")[1])
        span.set_attribute("retrieval.document.content", POLICY_DOCS[doc_id])
        return doc_id, POLICY_DOCS[doc_id]


def generate(question: str, context: str) -> str:
    with tracer.start_as_current_span("generate_answer") as span:
        amount = re.search(r"\$(\d+)", context).group(0)
        answer = f"You are owed {amount}, and we will cover return shipping."
        span.set_attribute("output.value", answer)
        return answer


def run_agent(question: str) -> str:
    with tracer.start_as_current_span("refund_agent") as span:
        span.set_attribute("input.value", question)
        _, context = retrieve(question)
        answer = generate(question, context)
        span.set_attribute("output.value", answer)
        span.set_status(Status(StatusCode.OK))
        return answer


def amounts(text: str) -> set[str]:
    return set(re.findall(r"\$\d+", text))


def evaluate(spans, expected_answer: str) -> dict:
    by_name = {s.name: s for s in spans}
    answer = by_name["refund_agent"].attributes["output.value"]
    retrieved = by_name["retrieve_policy"].attributes
    version = f'{retrieved["retrieval.document.id"]}@{retrieved["retrieval.document.version"]}'
    return {
        "context_check": int(amounts(answer) <= amounts(retrieved["retrieval.document.content"])),
        "reference_check": int(amounts(answer) == amounts(expected_answer)),
        "freshness_check": int(version == CURRENT_VERSION),
    }


if __name__ == "__main__":
    question = "My parcel arrived damaged. How much refund do I get?"
    expected = "You are owed $140, and we will cover return shipping."

    start = time.perf_counter()
    answer = run_agent(question)
    elapsed_ms = (time.perf_counter() - start) * 1000

    spans = exporter.get_finished_spans()
    root = next(s for s in spans if s.name == "refund_agent")
    report = {
        "answer": answer,
        "spans": [s.name for s in spans],
        "root_status": root.status.status_code.name,
        "error_spans": sum(s.status.status_code == StatusCode.ERROR for s in spans),
        "latency_ms": round(elapsed_ms, 2),
        "retrieved_version": next(s for s in spans if s.name == "retrieve_policy").attributes["retrieval.document.version"],
        "scores": evaluate(spans, expected),
    }
    print(json.dumps(report, indent=2))
