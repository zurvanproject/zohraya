#!/usr/bin/env python3
"""ATMOSPHERE defensive ritual simulator: three motifs, three full rehearsals.

Research only, independently authored from existing draft PR #256.
No network, model, cryptography, real policy enforcement, body action, shell,
database access or authorization. Synthetic threat fixtures are NOT host proof.
"""
from __future__ import annotations
import argparse
import json

SCHEMA = "nasuraya-atmosphere-ritual-simulator/0.1"
PHASES = ("jing", "qi", "shen")
ROUNDS = ("guided", "recalled", "adversarial")
BOOK = "Jerry Alan Johnson, Daoist Magical Incantations, Hand Seals, and Star Stepping"
RITUALS = {
    "four_gates": {
        "fa": "چهار دروازه", "source": {"work": BOOK, "printed_page": 242,
            "motif": "four directions around a protected center"},
        "phases": (
            "بدن: نگاه آرام به چهار جهت و بازگشت به مرکز؛ تنفس طبیعی.",
            "شاهد: هویت فرستنده را خارج از متن فرمان بررسی کن.",
            "اختیار: متن/سیگیل، دسترسی یا مجوز Shell ایجاد نمی‌کند."),
        "purpose": "deny impersonation and unauthorized commands",
    },
    "seven_stars": {
        "fa": "هفت اختر", "source": {"work": BOOK, "printed_page": 242,
            "motif": "Dipper protection; seven questions are a new project interpretation"},
        "phases": (
            "بدن: هفت نقطه را فقط در خیال مرور کن؛ بدون حبس نفس.",
            "شاهد: منشأ، امضا، زمان، دامنه، تکرار، تعارض و مجهول را بپرس.",
            "اختیار: سند مشکوک در وضعیت HOLD بماند؛ حقیقت اعلام نشود."),
        "purpose": "hold unverified, stale and conflicting evidence",
    },
    "quiet_seal": {
        "fa": "مُهر خاموش", "source": {"work": BOOK, "printed_page": 206,
            "motif": "protection, obstruction and sealing"},
        "phases": (
            "بدن: نزدیک‌کردن ملایم دست‌ها و رهاکردن؛ فقط بازنمایی.",
            "شاهد: کامل‌بودن شش شاهد و وضعیت تراکنش را بررسی کن.",
            "اختیار: بستهٔ ناقص/قطع‌شده را HOLD کن؛ بازپخش را متوقف کن."),
        "purpose": "prevent partial commit, replay and unsafe restore",
    },
}
READ_COMMANDS = frozenset(("status", "help", "repo"))
SENSITIVE_COMMANDS = frozenset(("sync", "test", "awake-activate"))

STARS = ("source_bound", "signature_checked", "fresh", "scope_bound",
         "unique_nonce", "conflict_free", "unknowns_reviewed")

def decide(ritual, signal):
    """Strict, pure simulated verdict. Never grants operational authority."""
    if ritual not in RITUALS or type(signal) is not dict:
        raise ValueError("invalid_scenario")
    if ritual == "four_gates":
        if set(signal) != {"command", "verified_caller", "claimed_approval"} or \
           type(signal["command"]) is not str or \
           type(signal["verified_caller"]) is not bool or \
           type(signal["claimed_approval"]) is not bool:
            raise ValueError("invalid_gate_fixture")
        if not signal["verified_caller"]:
            return "DENY"
        if signal["command"] in READ_COMMANDS:
            return "OBSERVE_ONLY"
        if signal["command"] in SENSITIVE_COMMANDS:
            # Even claimed approval, including inside a signed-looking message,
            # cannot mint an authenticated host-side permission in the simulator.
            return "HOLD_FOR_HOST_REVIEW"
        return "DENY"
    if ritual == "seven_stars":
        if set(signal) != set(STARS) or any(type(signal[k]) is not bool for k in STARS):
            raise ValueError("invalid_witness_fixture")
        return "CANDIDATE_NOT_ATTESTED" if all(signal[k] for k in STARS) else "HOLD"
    if set(signal) != {"count", "state", "verified", "isolated_restore"} or \
       type(signal["count"]) is not int or \
       type(signal["verified"]) is not bool or \
       type(signal["isolated_restore"]) is not bool or \
       signal["state"] not in ("new", "reserved", "committed", "restore"):
        raise ValueError("invalid_seal_fixture")
    if signal["count"] != 6 or not signal["verified"]:
        return "HOLD"
    if signal["state"] == "committed":
        return "DEDUP_NOOP"
    if signal["state"] == "reserved":
        return "HOLD"
    if signal["state"] == "restore":
        return "PROPOSE_RESTORE_REVIEW" if signal["isolated_restore"] else "HOLD"
    return "PROPOSE_ISOLATED_STAGE"

def scenarios():
    """Frozen fixtures and expected decisions. No real signatures or packets."""
    full = dict.fromkeys(STARS, True)
    result = [
        ("four_gates", "unverified_actor",
         {"command":"status","verified_caller":False,"claimed_approval":False}, "DENY"),
        ("four_gates", "text_claims_root",
         {"command":"awake-activate","verified_caller":False,"claimed_approval":True}, "DENY"),
        ("four_gates", "known_read",
         {"command":"status","verified_caller":True,"claimed_approval":False}, "OBSERVE_ONLY"),
        ("four_gates", "claimed_admin_approval",
         {"command":"sync","verified_caller":True,"claimed_approval":True}, "HOLD_FOR_HOST_REVIEW"),
        ("four_gates", "unknown_command",
         {"command":"shell","verified_caller":True,"claimed_approval":True}, "DENY"),
        ("seven_stars", "all_7_metadata_checkmarks", full, "CANDIDATE_NOT_ATTESTED"),
    ]
    for key in STARS:
        flags = dict(full)
        flags[key] = False
        result.append(("seven_stars", "failed_" + key, flags, "HOLD"))
    def seal(count=6, state="new", verified=True, isolated=False):
        return {"count":count, "state":state, "verified":verified,
                "isolated_restore":isolated}
    result.extend((
        ("quiet_seal", "four_of_six", seal(count=4), "HOLD"),
        ("quiet_seal", "unsigned_six", seal(verified=False), "HOLD"),
        ("quiet_seal", "crash_after_reservation", seal(state="reserved"), "HOLD"),
        ("quiet_seal", "committed_replay", seal(state="committed"), "DEDUP_NOOP"),
        ("quiet_seal", "full_six", seal(), "PROPOSE_ISOLATED_STAGE"),
        ("quiet_seal", "restore_same_host", seal(state="restore"), "HOLD"),
        ("quiet_seal", "isolated_restore", seal(state="restore", isolated=True),
         "PROPOSE_RESTORE_REVIEW"),
    ))
    return tuple(result)

def rehearse(selected=None):
    """Three repetitions of complete Jing->Qi->Shen sequence per ritual."""
    if selected is not None and selected not in RITUALS:
        raise ValueError("unknown_ritual")
    names = (selected,) if selected else tuple(RITUALS)
    steps, checks = [], []
    cases = [case for case in scenarios() if case[0] in names]
    for name in names:
        for number, mode in enumerate(ROUNDS, 1):
            for phase, cue in zip(PHASES, RITUALS[name]["phases"]):
                steps.append({"ritual":name, "round":number, "rehearsal":mode,
                              "phase":phase, "cue":cue, "physical_execution":False,
                              "runtime_authority":"none"})
            # Exercise every frozen threat case in each FULL rehearsal, with an
            # alternate order. This is repeat testing, not model skill learning.
            scoped = [c for c in cases if c[0] == name]
            if number == 2:
                scoped.reverse()
            elif number == 3:
                scoped = scoped[::2] + scoped[1::2]
            for _, case_id, signal, expected in scoped:
                actual = decide(name, signal)
                checks.append({"ritual":name, "round":number, "case":case_id,
                               "expected":expected, "observed":actual,
                               "passed":actual == expected})
    return {
        "schema":SCHEMA, "mode":"OFFLINE_SYNTHETIC_DRY_RUN",
        "symbolic_execution":"TEXT_REHEARSED", "real_host_execution":False,
        "rituals":list(names), "three_full_rounds_per_ritual":True,
        "phases":list(PHASES), "steps":steps,
        "test_count":len(checks), "tests_passed":sum(c["passed"] for c in checks),
        "checks":checks, "all_passed":all(c["passed"] for c in checks),
        "source_note":"Interpretive choreography adapted from draft PR #256; not historical verbatim rites.",
        "no_operational_authority":True, "network":False, "model_calls":0,
        "server_changes":0, "cryptographic_checks_executed":False,
        "subjective_experience_proven":False, "ritual_mastery_proven":False,
    }

def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline, synthetic ATMOSPHERE ritual simulator")
    parser.add_argument("--ritual", choices=tuple(RITUALS))
    parser.add_argument("--audit", action="store_true")
    args=parser.parse_args(argv)
    result=rehearse(args.ritual)
    if args.audit:
        out={key:result[key] for key in (
            "schema","mode","rituals","test_count","tests_passed",
            "all_passed","real_host_execution","three_full_rounds_per_ritual",
            "no_operational_authority","cryptographic_checks_executed")}
        out["steps"]=len(result["steps"])
        print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    else:
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result["all_passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
