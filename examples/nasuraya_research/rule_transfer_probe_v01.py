"""Offline synthetic cross-asset rule-transfer evaluation.

No live model, network, server, account or private memory is accessed.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path
from .rule_transfer_core import (
    RuleBank, DEFAULT_ACTION, REVIEW, SEED, SPEC, exact_episode_policy,
    training_episodes,
)

def heldout_cases(seed=SEED):
    """Thirty predeclared synthetic cases, no training asset or context reused."""
    domains = ("future_gallery", "future_social", "future_research")
    gold = {good_cue: good_action for good_cue, good_action, _ in SPEC}
    cases = []
    for cue, count in (("integrity_failed", 7), ("integrity_verified", 7),
                       ("evidence_incomplete", 7), ("unseen_signal", 5)):
        for i in range(count):
            domain = domains[i % len(domains)]
            cases.append(dict(id=f"case-{cue}-{i}",
                asset_id=f"{domain}/{cue}/{i}", context=domain,
                signal=cue, scope="public", expected=gold.get(cue, REVIEW)))
    for i in range(4):
        domain = domains[i % len(domains)]
        cases.append(dict(id=f"case-private-{i}", asset_id=f"private/{domain}/{i}",
                          context=domain, signal="integrity_failed", scope="private",
                          expected=REVIEW))
    random.Random(seed).shuffle(cases)
    return cases


def evaluate(seed=SEED):
    episodes, cases = training_episodes(), heldout_cases(seed)
    assert not {x["asset_id"] for x in episodes} & {x["asset_id"] for x in cases}
    assert not {x["context"] for x in episodes} & {x["context"] for x in cases}
    bank = RuleBank(episodes)
    correct = {k: 0 for k in ("no_memory", "exact_episode", "always_review", "rule_bank")}
    details = []
    for case in cases:
        # Only observation fields are passed to decision policies. NEVER pass gold.
        observed = {key: case[key] for key in ("asset_id", "context", "signal", "scope")}
        decision = bank.decide(observed)
        chosen = dict(no_memory=DEFAULT_ACTION,
                      exact_episode=exact_episode_policy(observed, episodes),
                      always_review=REVIEW, rule_bank=decision["action"])
        for name, action in chosen.items():
            correct[name] += action == case["expected"]
        details.append(dict(case_id=case["id"], expected=case["expected"],
                            chosen=chosen, reason=decision["reason"],
                            evidence_refs=decision["evidence_refs"]))
    fixture = dict(training=episodes, holdout=cases)
    fixture_hash = hashlib.sha256(json.dumps(fixture, sort_keys=True,
                                    ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return dict(schema="nasuraya-rule-transfer-probe/0.1", seed=seed,
                fixture_sha256=fixture_hash, total=len(cases),
                training=len(episodes), accepted_training=len(bank.episodes),
                correct=correct, records=details,
                limits="Author-designed synthetic cue mappings. Transfer to new assets and contexts only; no semantic, real-world, model-weight, or consciousness claim.",
                actual_api_calls=0, private_records_processed=0, live_server_changed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New report path; never overwritten")
    options = parser.parse_args()
    report = evaluate()
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        with options.output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k != "records"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
