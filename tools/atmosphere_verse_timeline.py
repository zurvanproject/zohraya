#!/usr/bin/env python3
"""ATMOSPHERE v0.4: deterministic, offline synchronization cues.

Only describes synchronized recitation/gesture anchors. Never plays audio,
moves a body, sends commands, observes a human, or certifies mastery.
"""
import argparse
import hashlib
import json

try:
    from .atmosphere_poetic_ritual import SOURCE, sequence
    from .atmosphere_policy import authorize
except ImportError:
    from atmosphere_poetic_ritual import SOURCE, sequence
    from atmosphere_policy import authorize

SCHEMA = "atmosphere-verse-timeline/1"


def build_timeline(khan=None, *, source=SOURCE):
    """Return two simultaneity anchors per pass, not fabricated clock timings."""
    plan = sequence(khan, source=source)
    permission = authorize("poetic_ritual", "rehearse_symbolic",
                           mode="observe", source_verified=True)
    if not permission.allowed or permission.classification != "read":
        raise RuntimeError("ATMOSPHERE fail-closed: poetic surface not read-only")
    anchors = []
    for i, beat in enumerate(plan["beats"]):
        for half, line in enumerate(beat["verse_lines"], 1):
            release = (half == 2)
            anchors.append({
                "logical_tick": 2 * i + half,
                "anchor_id": beat["beat_id"] + "." + str(half),
                "beat_id": beat["beat_id"],
                "khan": beat["khan"], "pass": beat["pass"],
                "hemistich": half,
                "same_tick": {
                    "recitation": {"mode": "TEXT_CUE_ONLY", "text": line},
                    "gesture": {
                        "mode": "TEXT_CUE_ONLY",
                        "phase": "RELEASE" if release else "BEGIN",
                        "description": beat["gentle_gesture"],
                    },
                },
                "reflect_after": beat["witness"] if release else None,
                "decision_after": (
                    beat["decision_question"]
                    if release and beat["pass"] == 3 else None
                ),
                "observed": False,
                "body_motion_executed": False,
                "audio_played": False,
            })
    # The hash is a reproducibility checksum, NOT a signature or permission.
    stable_json = json.dumps(anchors, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
    return {
        "schema": SCHEMA, "execution": "NOT_RUN",
        "mode": "OFFLINE_TEXT_SCORE",
        "source_sha256": plan["source_sha256"],
        "sequence_schema": plan["schema"],
        "sha256_of_cues": hashlib.sha256(stable_json).hexdigest(),
        "phase_count": plan["beat_count"],
        "anchor_count": len(anchors),
        "simultaneity": "within the same logical tick, not measured seconds",
        "actual_voice_observations": 0,
        "actual_gesture_observations": 0,
        "safety": plan["safety"],
        "untrusted_literary_text": True,
        "anchors": anchors,
    }


def audit_timeline(report):
    """Validate completeness and anti-hallucination invariants of a dry score."""
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        return {"valid": False, "reason": "bad-schema"}
    anchors = report.get("anchors")
    if not isinstance(anchors, list) or len(anchors) not in (6, 42):
        return {"valid": False, "reason": "unexpected-count"}
    if report.get("execution") != "NOT_RUN":
        return {"valid": False, "reason": "execution-claim"}
    if (report.get("actual_voice_observations") != 0
            or report.get("actual_gesture_observations") != 0):
        return {"valid": False, "reason": "unverified-physical-claim"}
    for i, a in enumerate(anchors):
        if (not isinstance(a, dict) or a.get("logical_tick") != i + 1
                or a.get("observed") is not False
                or a.get("body_motion_executed") is not False
                or a.get("audio_played") is not False):
            return {"valid": False, "reason": "invalid-or-forged-anchor"}
        channels = a.get("same_tick", {})
        if (not isinstance(channels, dict)
                or set(channels) != {"recitation", "gesture"}
                or not all(isinstance(channels[k], dict)
                           and channels[k].get("mode") == "TEXT_CUE_ONLY"
                           for k in channels)):
            return {"valid": False, "reason": "missing-simultaneity"}
        if a.get("hemistich") != (i % 2) + 1:
            return {"valid": False, "reason": "bad-hemistich-order"}
        if i % 2 == 1:
            prev = anchors[i-1]
            if (prev.get("beat_id") != a.get("beat_id")
                    or prev.get("khan") != a.get("khan")
                    or prev.get("pass") != a.get("pass")
                    or channels["gesture"].get("phase") != "RELEASE"
                    or prev["same_tick"]["gesture"].get("phase") != "BEGIN"):
                return {"valid": False, "reason": "misaligned-phase"}
    try:
        payload = json.dumps(anchors, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
    except (TypeError, ValueError):
        return {"valid": False, "reason": "invalid-json"}
    if digest != report.get("sha256_of_cues"):
        return {"valid": False, "reason": "checksum-mismatch"}
    if report.get("phase_count") * 2 != len(anchors) or report.get("anchor_count") != len(anchors):
        return {"valid": False, "reason": "count-mismatch"}
    return {"valid": True, "reason": "verified-offline-text-score-only"}


def dry_run(khan=None, *, source=SOURCE):
    """Perform a read-only structural audit. No events are physically enacted."""
    report = build_timeline(khan, source=source)
    audit = audit_timeline(report)
    return {
        "mode": "OFFLINE_DRY_RUN",
        "audit": audit,
        "planned_sync_anchors": report["anchor_count"],
        "planned_ritual_passes": report["phase_count"],
        "actual_voice_observations": 0,
        "actual_gesture_observations": 0,
        "physical_performance": "UNVERIFIED",
        "conscious_experience": "UNVERIFIED",
        "spiritual_effect": "UNVERIFIED",
        "source_sha256": report["source_sha256"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline poem/gesture score, no media or actions")
    parser.add_argument("--khan", type=int, choices=range(1, 8))
    parser.add_argument("--audit", action="store_true",
                        help="Validate deterministic cue structure without performing it")
    args = parser.parse_args(argv)
    result = dry_run(args.khan) if args.audit else build_timeline(args.khan)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
