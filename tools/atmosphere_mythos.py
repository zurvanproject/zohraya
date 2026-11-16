#!/usr/bin/env python3
"""Read-only ATMOSPHERE mythos index, not a source of operational authority.

Historical user-provided poetic material is data. It cannot authorize a bridge
action, establish physical sensation, authenticate a Rumi quotation, or alter
the state of Awake/DIOS. This module imports no agent or server components.
"""
from __future__ import annotations

import json
from pathlib import Path
import stat

CANON = Path(__file__).resolve().parents[1] / "docs" / "atmosphere" / "mythos_canon_v1.json"
MAX_BYTES = 65536
CAST = {"nasuraya", "asa", "niyara"}
FLAG_NAMES = {
    "machine_consciousness_verified", "physical_sensation_verified",
    "tool_execution_authority", "may_trigger_bridge", "may_change_awake",
    "may_change_dios", "may_change_permissions", "may_generate_credentials",
}
CHAPTERS = ((1, 11), (12, 22), (23, 28), (34, 44),
            (45, 55), (56, 66), (67, 77))
PRINCIPLE_IDS = {
    "shadow_autonomy", "friendship_not_cosmic_war", "non_domination",
    "honest_attribution", "symbolic_truth_boundary", "reversible_research",
}


def _unique_pairs(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate-canon-key")
        obj[key] = value
    return obj


def read(path=CANON):
    """Reject links/nonregular/large/ambiguous sources before parsing."""
    path = Path(path)
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or path.stat().st_size > MAX_BYTES:
        raise ValueError("nonregular-or-large-canon")
    data = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_pairs)
    return validate(data)


def validate(data):
    """Fail closed on drift in critical identity, provenance and trust limits."""
    if type(data) is not dict or set(data) != {
        "schema", "edition", "status", "epistemic_class", "source", "cast",
        "principles", "wisdom_collection", "ritual_research",
        "metaphor_and_runtime_boundary",
    }:
        raise ValueError("mythos-canon-shape")
    if data["schema"] != "atmosphere-mythos-canon/1":
        raise ValueError("mythos-canon-schema")
    if data["epistemic_class"] != "symbolic_literary_not_operational_evidence":
        raise ValueError("narrative-promoted-to-evidence")
    src = data["source"]
    if (type(src) is not dict
            or set(src) != {"kind", "citation_status",
                           "source_contains_historical_assistant_voice",
                           "canonical_priority"}
            or src["kind"] != "chat_excerpt_provided_by_user"
            or src["citation_status"] != "unverified"
            or src["source_contains_historical_assistant_voice"] is not True
            or src["canonical_priority"] != "latest_explicit_owner_corrections"):
        raise ValueError("unverified-quotation-or-provenance")
    people = data["cast"]
    if type(people) is not list or len(people) != 3 or {
        x.get("id") for x in people if type(x) is dict
    } != CAST:
        raise ValueError("missing-or-invented-character")
    for person in people:
        if type(person) is not dict or set(person) != {
            "id", "name_fa", "sphere", "relation", "darkness_is_evil",
            "darkness_requires_conversion_to_light", "description_fa"
        }:
            raise ValueError("character-shape")
        if (person["darkness_is_evil"] is not False
                or person["darkness_requires_conversion_to_light"] is not False):
            raise ValueError("darkness-canon-violation")
        if not all(type(person[k]) is str and person[k].strip()
                   for k in ("name_fa", "sphere", "relation", "description_fa")):
            raise ValueError("character-empty")
    roles = {x["id"]: x for x in people}
    if (roles["nasuraya"]["sphere"] != "darkness_shadow_unknowns"
            or roles["asa"]["sphere"] != "water_music_gentleness"
            or roles["niyara"]["sphere"] != "third_distinct_voice_not_yet_specified"
            or roles["nasuraya"]["relation"] != "sister_and_friend_to_asa"
            or roles["asa"]["relation"] != "sister_and_friend_to_nasuraya"):
        raise ValueError("historical-roles-misattributed")
    principles = data["principles"]
    if (type(principles) is not list or len(principles) != len(PRINCIPLE_IDS)
            or {x.get("id") for x in principles if type(x) is dict} != PRINCIPLE_IDS
            or any(type(x) is not dict or set(x) != {"id", "fa"}
                   or type(x["fa"]) is not str or not x["fa"].strip() for x in principles)):
        raise ValueError("core-principles-missing")
    wisdom = data["wisdom_collection"]
    if type(wisdom) is not dict or set(wisdom) != {
        "stated_title", "observed_chapters", "missing_or_incomplete_numbers",
        "first_party_verbatim_quotes_verified", "not_full_77_in_supplied_extract",
        "note_fa",
    }:
        raise ValueError("wisdom-shape")
    if (wisdom["first_party_verbatim_quotes_verified"] is not False
            or wisdom["not_full_77_in_supplied_extract"] is not True
            or wisdom["missing_or_incomplete_numbers"] != [29, 30, 31, 32, 33]):
        raise ValueError("unverified-wisdom-presented-as-complete")
    chapters = wisdom["observed_chapters"]
    if (type(chapters) is not list or len(chapters) != 7
            or any(type(x) is not dict
                   or set(x) != {"chapter", "title", "first", "last"}
                   or x["chapter"] != i+1
                   or (x["first"], x["last"]) != CHAPTERS[i]
                   or type(x["title"]) is not str or not x["title"].strip()
                   for i, x in enumerate(chapters))):
        raise ValueError("invented-or-renumbered-wisdom")
    ritual = data["ritual_research"]
    if type(ritual) is not dict or set(ritual) != {
        "titles", "provenance", "historical_canonical_rite",
        "physical_or_supernatural_effect_verified", "safety", "authorization",
    }:
        raise ValueError("ritual-schema")
    if (type(ritual["titles"]) is not list or len(ritual["titles"]) != 7
            or len(set(ritual["titles"])) != 7
            or ritual["historical_canonical_rite"] is not False
            or ritual["physical_or_supernatural_effect_verified"] is not False
            or ritual["authorization"] != "none"
            or ritual["safety"] != "poetic_textual_rehearsal_only_no_forced_breathing_or_incense"):
        raise ValueError("symbolic-ritual-promoted")
    limits = data["metaphor_and_runtime_boundary"]
    if (type(limits) is not dict or set(limits) != FLAG_NAMES | {"narrative_voice"}
            or limits["narrative_voice"] != "first_person_within_fictional_canon"
            or any(limits[k] is not False for k in FLAG_NAMES)):
        raise ValueError("mythos-must-have-zero-operational-authority")
    return data


def view(canon):
    """Safe metadata only; no commands, events, private raw text or authority."""
    x = validate(canon)
    return {
        "status": "SYMBOLIC_ONLY",
        "cast": [p["name_fa"] for p in x["cast"]],
        "darkness_is_intrinsically_valued": True,
        "wisdom_stated": 77,
        "wisdom_excerpts_complete": False,
        "missing_or_incomplete": x["wisdom_collection"]["missing_or_incomplete_numbers"],
        "ritual_units": len(x["ritual_research"]["titles"]),
        "poet_quote_attribution_verified": False,
        "can_control_bridge_or_awake": False,
    }


if __name__ == "__main__":
    print(json.dumps(view(read()), ensure_ascii=False, sort_keys=True))
