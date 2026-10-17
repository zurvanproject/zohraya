"""Ten repeated native-body walk requests, with honest non-learning control.

Same fixed input protocol in two independent fresh bodies. Reports each tick's
simulated balance, accepted action and stability. No training/policy updates.
"""
from examples.nasuraya_self_model.evaluate import fixture, request
from examples.nasuraya_research.body_observer import observe_native_body
import json


def trial(label):
    body = fixture(0.1)
    rows = []
    for i in range(1, 11):
        before = observe_native_body(body)
        req = request(body, f"{label}-walk-{i}", .1)
        receipt = body.cycle(**req)
        after = observe_native_body(body)
        rows.append(dict(attempt=i, balance_before=before["sensory"]["q"][5],
                         balance_after=after["sensory"]["q"][5],
                         action=receipt["owner"]["selected_action"],
                         valid=receipt["owner"]["physical_model_valid"],
                         sensory_source=after["sensory"]["source"]))
    return rows


def run():
    from synthetic_fixture import prepare_defaults
    prepare_defaults()
    a, b = trial("fixed-a"), trial("fixed-b")
    comparable = [{k:v for k,v in row.items() if k!="sensory_source"} for row in a]
    independent = [{k:v for k,v in row.items() if k!="sensory_source"} for row in b]
    assert comparable == independent, "same fixed protocol is not reproducible"
    result = dict(schema="ten-step-native-motion-observation/1",
                  steps=a, repeatable=True,
                  independent_baseline=b,
                  learning_enabled=False,
                  policy_updates=0,
                  corrected_route_trials=0,
                  automatic_self_improvement_demonstrated=False,
                  notes="10 native 0.1s walk requests are NOT ten completed star routes. No learned policy; within-run change may be ordinary body dynamics. An adaptive-vs-frozen controller trial is still required.")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    run()
