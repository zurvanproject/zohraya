"""Ten repeated native-body walk requests, with honest non-learning control.

Same fixed input protocol in two independent fresh bodies. Reports each tick's
simulated balance, accepted action and stability. No training/policy updates.
"""
from examples.nasuraya_self_model.evaluate import fixture, request
from examples.nasuraya_research.body_observer import observe_native_body
import json
from copy import deepcopy
from .dream_ten_native import stride_reference, measure_step


def trial(label):
    body = fixture(0.1)
    rows = []
    reference = stride_reference(body)
    for i in range(1, 11):
        before = observe_native_body(body)
        feet_before = deepcopy(body.owner.physical.state.feet_m)
        req = request(body, f"{label}-walk-{i}", .1)
        receipt = body.cycle(**req)
        after = observe_native_body(body)
        rows.append(dict(attempt=i, balance_before=before["sensory"]["q"][5],
                         balance_after=after["sensory"]["q"][5],
                         action=receipt["owner"]["selected_action"],
                         valid=receipt["owner"]["physical_model_valid"],
                         sensory_source=after["sensory"]["source"],
                         measurement=measure_step(body, receipt, reference,
                             before["sensory"]["q"][5], feet_before)))
    return rows


def run():
    from synthetic_fixture import prepare_defaults
    prepare_defaults()
    a, b = trial("fixed-a"), trial("fixed-b")
    def physical_rows(rows):
        # Different event IDs produce different receipt/checkpoint hashes.
        copies = deepcopy(rows)
        for row in copies:
            row.pop('sensory_source')
            row['measurement'].pop('native_checkpoint_sha256')
            row['measurement'].pop('receipt_sha256')
        return copies
    comparable, independent = physical_rows(a), physical_rows(b)
    assert comparable == independent, "same fixed protocol is not reproducible"
    result = dict(schema="ten-step-native-motion-observation/2",
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
