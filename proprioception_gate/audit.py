"""Fail-closed, read-only audit of a synthetic proprioception ZIP.
Never executes archive code. Arithmetic PASS != validated dynamics or safety.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile

ROOT = "NASURAYA_PROPRIOCEPTION_V1/"
REQUIRED = (
    "zohraya_proprioception/proprioception_engine.py",
    "zohraya_proprioception/self_model_decision_bridge.py",
    "data/simulation_scenarios_results.json",
    "data/learning_benchmark_holdout.json",
    "visualization/proprioception_viewer.html",
    "tests/test_proprioception_suite.py",
    "README_FA.md", "SHA256SUMS.txt",
)
LIMITS = {
    "J_C0_C1": ((-45, 55), 52),
    "J_LUMBAR": ((-35, 65), 240),
    "J_SACROCAUDAL": ((-65, 95), 48),
    "J_HIP_L": ((-35, 130), 260), "J_HIP_R": ((-35, 130), 260),
    "J_KNEE_L": ((-155, -12), 245), "J_KNEE_R": ((-155, -12), 245),
    "J_ANKLE_TARSAL_L": ((15, 85), 210),
    "J_ANKLE_TARSAL_R": ((15, 85), 210),
    "J_MTP_3TOES_L": ((-45, 65), 95),
    "J_MTP_3TOES_R": ((-45, 65), 95),
}


def finite(value, name):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(name + " must be a finite numeric value")
    return float(value)


def vector(value, name, n=3):
    if not isinstance(value, (tuple, list)) or len(value) != n:
        raise ValueError(name + " must have " + str(n) + " components")
    return [finite(v, name) for v in value]


def check_scenario(row, index):
    issues = []
    tag = "scenario[" + str(index) + "]"
    try:
        pred = row["prediction"]
        actual = row["simulation_outcome"]
        action = row["action_proposal"]
        expected_error = math.dist(
            vector(pred["predicted_com_m"], "predicted COM"),
            vector(actual["actual_com_m"], "synthetic outcome")
        ) * 1000
        reported_error = finite(row["prediction_error_norm_mm"], "COM error")
        if abs(expected_error - reported_error) > .025:
            issues.append(tag + ": prediction-error report disagrees with supplied positions")
        c = pred["eui_components"]
        fractions = [finite(c[name], name) for name in (
            "mos_deficit", "torque_saturation", "slip_ratio_index", "sensor_degradation")]
        if any(v < 0 or v > 1.0001 for v in fractions):
            issues.append(tag + ": EUI component outside [0,1]")
        recomputed = max(0., min(1.,
            .4*fractions[0] + .25*fractions[1] + .2*fractions[2] + .15*fractions[3]))
        eui = finite(pred["engineering_uncertainty_index_eui"], "EUI")
        if not 0 <= eui <= 1 or abs(recomputed - eui) > .00025:
            issues.append(tag + ": EUI arithmetic disagrees")
        band = ("NOMINAL_STABLE" if eui < .35 else
                "GUARDED_ACTIVE_COMPENSATION" if eui < .65 else
                "HIGH_INSTABILITY_RISK")
        if pred["risk_classification"] != band:
            issues.append(tag + ": risk label disagrees with EUI")
        mos = finite(pred["predicted_mos_m"], "margin of stability")
        if type(pred["support_sufficient"]) is not bool or pred["support_sufficient"] != (mos >= 0):
            issues.append(tag + ": support boolean contradicts MoS")
        if action.get("safety_guard_verified") is not True:
            issues.append(tag + ": local guard flag is not True")
        for joint, torque in action["joint_torques_nm"].items():
            t = finite(torque, joint + " torque")
            if joint not in LIMITS:
                issues.append(tag + ": unknown torque joint " + joint)
            elif abs(t) > LIMITS[joint][1] + .0001:
                issues.append(tag + ": torque exceeds nominal guard " + joint)
        for joint, angle in action["target_joint_angles_deg"].items():
            a = finite(angle, joint + " angle")
            if joint not in LIMITS:
                issues.append(tag + ": unknown angle joint " + joint)
            else:
                low, high = LIMITS[joint][0]
                if not low - .0001 <= a <= high + .0001:
                    issues.append(tag + ": angle exceeds nominal guard " + joint)
    except (TypeError, ValueError, KeyError, AttributeError) as error:
        issues.append(tag + ": bad or missing data: " + str(error))
    return issues


def audit_archive(path):
    problems = []
    warnings = [
        "Arithmetic consistency is not evidence of physical stability or safety.",
        "No motor code in this ZIP was executed, and no actual sensors were validated.",
        "Report labels such as safety_guard_verified are not safety certifications.",
        "Support areas in supplied source are axis-aligned rectangles, not actual 3-toe polygons.",
    ]
    result = dict(schema="nasuraya-proprioception-external-audit/1",
                  archive=str(path), status="BLOCKED",
                  failures=problems, limitations=warnings,
                  physically_validated_scenarios=0,
                  checked_synthetic_scenarios=0)
    try:
        with zipfile.ZipFile(path) as zf:
            entries = zf.infolist()
            if len(entries) > 300 or sum(i.file_size for i in entries) > 40_000_000:
                raise ValueError("archive count or size exceeds limits")
            names = [i.filename for i in entries if not i.is_dir()]
            if len(names) != len(set(names)):
                raise ValueError("duplicate archive entries")
            for info in entries:
                name = info.filename
                if (not name.startswith(ROOT) or name.startswith("/") or
                        "\\" in name or ".." in PurePosixPath(name).parts or
                        info.file_size > 15_000_000 or "\x00" in name):
                    raise ValueError("unsafe archive path or size: " + name)
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise ValueError("symlink in archive: " + name)
            if any(ROOT + x not in names for x in REQUIRED):
                raise ValueError("a mandatory archive file is missing")
            manifests = zf.read(ROOT + "SHA256SUMS.txt").decode("utf-8")
            expected = {}
            for line in manifests.splitlines():
                match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
                if not match or match.group(2) in expected:
                    raise ValueError("invalid or duplicated SHA256 entry")
                expected[match.group(2)] = match.group(1)
            included = set(p.removeprefix(ROOT) for p in names) - {"SHA256SUMS.txt"}
            if set(expected) != included:
                raise ValueError("SHA256 manifest does not cover exact members")
            for rel, value in expected.items():
                if hashlib.sha256(zf.read(ROOT + rel)).hexdigest() != value:
                    problems.append("SHA256 mismatch: " + rel)
            if problems:
                return result
            data = json.loads(zf.read(ROOT + "data/simulation_scenarios_results.json"))
            records = data.get("scenarios")
            if not isinstance(records, list) or len(records) != 10 or data.get("scenarios_count") != 10:
                problems.append("expected ten structured synthetic scenarios")
            else:
                for index, record in enumerate(records):
                    problems.extend(check_scenario(record, index))
                result["checked_synthetic_scenarios"] = len(records)
            b = json.loads(zf.read(ROOT + "data/learning_benchmark_holdout.json"))
            pre, post = finite(b["pre_adaptation_rmse_mm"], "pre-RMSE"), finite(b["post_adaptation_rmse_mm"], "post-RMSE")
            claimed = finite(b["relative_error_reduction_pct"], "improvement")
            if pre <= 0 or post < 0 or abs(100 * (1 - post / pre) - claimed) > .1:
                problems.append("holdout error-reduction arithmetic inconsistent")
            if "25" in str(b.get("evaluation_protocol", "")):
                warnings.append("The supplied code evaluates 25, not the prose's 50, holdout cases.")
            warnings.append("Aggregate holdout scores cannot prove disjoint training/test samples.")
            result["verified_manifest_entries"] = len(expected)
            if not problems:
                result["status"] = "ARITHMETICALLY_CONSISTENT_NOT_PHYSICALLY_VALIDATED"
    except (OSError, zipfile.BadZipFile, TypeError, ValueError, KeyError,
            json.JSONDecodeError, UnicodeDecodeError) as error:
        problems.append(str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_file", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit_archive(args.zip_file)
    encoded = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    print(encoded)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return 0 if not result["failures"] and result["status"].startswith("ARITHMETICALLY_") else 1


if __name__ == "__main__":
    sys.exit(main())
