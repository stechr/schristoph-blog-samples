"""Score one captured session with AgentCore Evaluations (on-demand Evaluate API)."""
import json, sys
import boto3

spans = json.load(open(sys.argv[1]))
summary = json.load(open(sys.argv[1].replace(".json", "-summary.json")))
c = boto3.client("bedrock-agentcore", region_name="us-east-1")
trace_id = summary["trace_id"]
sess = summary["session_id"]
expected = "You are owed a $140 credit for the late delivery, and return shipping is covered."

runs = [
    ("Builtin.Faithfulness", None),
    ("Builtin.Helpfulness", None),
    ("Builtin.Correctness", None),
    ("Builtin.Correctness", expected),
]
out = []
for ev, ref in runs:
    kw = dict(evaluatorId=ev, evaluationInput={"sessionSpans": spans},
              evaluationTarget={"traceIds": [trace_id]})
    if ref:
        kw["evaluationReferenceInputs"] = [{
            "context": {"spanContext": {"sessionId": sess, "traceId": trace_id}},
            "expectedResponse": {"text": ref}}]
    try:
        r = c.evaluate(**kw)
        for res in r.get("evaluationResults", []):
            res.pop("evaluatorArn", None)
            out.append({"evaluator": ev, "with_expected_response": bool(ref), **res})
    except Exception as e:  # record, do not crash
        out.append({"evaluator": ev, "with_expected_response": bool(ref), "error": f"{type(e).__name__}: {e}"})

json.dump(out, open(sys.argv[2], "w"), indent=2, default=str)
for o in out:
    print(o["evaluator"], "ref" if o["with_expected_response"] else "noref",
          o.get("value"), o.get("label"), (o.get("error") or o.get("errorMessage") or "")[:300])
    if o.get("explanation"):
        print("   ", o["explanation"][:600].replace("\n", " "))
