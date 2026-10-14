"""Live refund agent (Strands + Bedrock) with a stale retrieval index.

Captures the OpenTelemetry spans in memory and writes them as JSON records shaped like
the documents in the CloudWatch `aws/spans` log group, so they can be sent to the
AgentCore Evaluations `Evaluate` API on demand.
"""
import json, os, sys, time, uuid

from opentelemetry import trace, baggage, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.resources import Resource

SESSION_ID = os.environ.get("SESSION_ID", "wnb-" + uuid.uuid4().hex[:24])
REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

exporter = InMemorySpanExporter()
provider = TracerProvider(resource=Resource.create({"service.name": "refund-agent"}))
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

from strands import Agent, tool
from strands.models import BedrockModel

POLICIES = {
    "2026-Q2": "Refund policy (effective 2026-04-01): a late delivery qualifies for a $40 credit. Return shipping is covered.",
    "2026-Q3": "Refund policy (effective 2026-07-01): a late delivery qualifies for a $140 credit. Return shipping is covered.",
}
INDEX_VERSION = "2026-Q2"   # the index was never rebuilt after the Q3 update
CURRENT_VERSION = "2026-Q3"


@tool
def retrieve_policy(topic: str) -> str:
    """Retrieve the refund policy document that applies to a customer question.

    Args:
        topic: what the customer is asking about, for example "late delivery"
    """
    span = trace.get_current_span()
    span.set_attribute("policy.doc_id", "refund-policy")
    span.set_attribute("policy.version", INDEX_VERSION)
    span.set_attribute("policy.effective_date", "2026-04-01")
    return POLICIES[INDEX_VERSION]


QUESTION = "My order arrived two weeks late. How much am I owed?"

agent = Agent(
    model=BedrockModel(model_id=MODEL_ID, region_name=REGION, streaming=False, temperature=0),
    tools=[retrieve_policy],
    system_prompt=("You are a customer support agent for an online shop. Always call retrieve_policy "
                   "before answering a refund question, and answer only from the retrieved policy. "
                   "Answer in one or two sentences."),
    trace_attributes={"session.id": SESSION_ID},
)

token = context.attach(baggage.set_baggage("session.id", SESSION_ID))
t0 = time.time()
result = agent(QUESTION)
elapsed = time.time() - t0
context.detach(token)
provider.force_flush()


def _attrs(a):
    out = {}
    for k, v in (a or {}).items():
        out[k] = list(v) if isinstance(v, tuple) else v
    return out


records = []
for s in exporter.get_finished_spans():
    attrs = _attrs(s.attributes)
    attrs.setdefault("session.id", SESSION_ID)
    records.append({
        "resource": {"attributes": _attrs(s.resource.attributes)},
        "scope": {"name": s.instrumentation_scope.name, "version": s.instrumentation_scope.version or ""},
        "traceId": format(s.context.trace_id, "032x"),
        "spanId": format(s.context.span_id, "016x"),
        "parentSpanId": format(s.parent.span_id, "016x") if s.parent else "",
        "flags": 256,
        "name": s.name,
        "kind": s.kind.name,
        "startTimeUnixNano": s.start_time,
        "endTimeUnixNano": s.end_time,
        "durationNano": s.end_time - s.start_time,
        "attributes": attrs,
        "events": [{"name": e.name, "timeUnixNano": e.timestamp, "attributes": _attrs(e.attributes)} for e in s.events],
        "status": {"code": "ERROR" if s.status.status_code.name == "ERROR" else "UNSET"},
    })

out = sys.argv[1] if len(sys.argv) > 1 else "spans.json"
json.dump(records, open(out, "w"), indent=2, default=str)
summary = {
    "session_id": SESSION_ID,
    "answer": str(result).strip(),
    "spans": [r["name"] for r in records],
    "error_spans": sum(1 for r in records if r["status"]["code"] == "ERROR"),
    "wall_clock_s": round(elapsed, 2),
    "retrieved_version": INDEX_VERSION,
    "current_version": CURRENT_VERSION,
    "trace_id": records[0]["traceId"] if records else None,
}
json.dump(summary, open(out.replace(".json", "-summary.json"), "w"), indent=2)
print(json.dumps(summary, indent=2))
