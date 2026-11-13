"""Private, local research ledger for the two simulated Tadash body readouts.

Records agreement *and disagreement* after source, timestep and command checks.
A reproducible hash chain catches corruption, not adversarial re-signing. This
is not connected to live Tadash, VPS, the agent's hidden memory, or hardware.
"""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from experiments.tadash_body_episode_memory import (
    GENESIS, IntegrityError, canonical, digest, valid_identifier,
)
from experiments.tadash_dual_sense import fuse_body_evidence
from experiments.tadash_embodied_origin import source_identity

STATES = frozenset((
    "no_detectable_change",
    "command_consistent",
    "agreement_unattributed_change",
    "agreement_command_mismatch",
    "sensor_disagreement",
    "uncertain_noise_or_missing",
))
UNCERTAIN = frozenset(("sensor_disagreement","uncertain_noise_or_missing"))


class DualEpisodeMemory:
    def __init__(self, path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(str(self.path),timeout=10,isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""CREATE TABLE IF NOT EXISTS dual_sessions (
            session_id TEXT PRIMARY KEY,
            last_ordinal INTEGER NOT NULL,
            head_hash TEXT NOT NULL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS dual_events (
            session_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL,
            event_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            PRIMARY KEY(session_id,ordinal),
            UNIQUE(session_id,event_id),
            FOREIGN KEY(session_id) REFERENCES dual_sessions(session_id)
        )""")

    def close(self):
        self.db.close()

    def _read(self,session_id):
        row=self.db.execute("SELECT last_ordinal,head_hash FROM dual_sessions "
                            "WHERE session_id=?",(session_id,)).fetchone()
        stored=self.db.execute("SELECT ordinal,event_id,payload_json,prev_hash,event_hash "
                               "FROM dual_events WHERE session_id=? ORDER BY ordinal",
                               (session_id,)).fetchall()
        if row is None:
            if stored:
                raise IntegrityError("dual_orphan_event")
            return 0,GENESIS,[]
        prior=GENESIS
        records=[]
        for number,(ordinal,event_id,payload_json,prev_hash,event_hash) in enumerate(stored,1):
            if ordinal!=number or prior!=prev_hash:
                raise IntegrityError("dual_sequence_discontinuous")
            try:
                payload=json.loads(payload_json)
                if canonical(payload)!=payload_json:
                    raise IntegrityError("dual_noncanonical_json")
            except (ValueError,TypeError) as exc:
                raise IntegrityError("dual_invalid_json") from exc
            if (payload.get("schema")!="tadash.dual-body-episode.v0.3" or
                    payload.get("session_id")!=session_id or
                    payload.get("event_id")!=event_id or
                    payload.get("ordinal")!=ordinal or
                    payload.get("assessment_state") not in STATES):
                raise IntegrityError("dual_event_identity_or_state_changed")
            computed=digest(prior+"\n"+payload_json)
            if computed!=event_hash:
                raise IntegrityError("dual_hash_mismatch")
            prior=computed
            records.append(payload)
        if row!=(len(stored),prior):
            raise IntegrityError("dual_head_mismatch")
        return len(stored),prior,records

    def snapshot(self,session_id):
        if not valid_identifier(session_id):
            raise ValueError("invalid_session_id")
        n,head,rows=self._read(session_id)
        return {"session_id":session_id,"count":n,"head":head,"events":rows}

    def append(self, session_id, event_id, ordinal, command_nm,
               reference, prediction, observation):
        if not all(valid_identifier(x) for x in (session_id,event_id)):
            raise ValueError("invalid_event_identity")
        if type(ordinal) is not int or ordinal<1:
            raise ValueError("invalid_ordinal")
        if type(command_nm) not in (int,float) or not math.isfinite(command_nm):
            raise ValueError("invalid_command")
        accepted_sha=source_identity()["sha256"]
        for trace in (reference,prediction,observation):
            if (not isinstance(trace,dict) or
                    not all(modality in trace and isinstance(trace[modality],dict)
                            for modality in ("primary","pose")) or
                    any(trace[mode].get("source_sha256")!=accepted_sha
                        for mode in ("primary","pose"))):
                raise ValueError("source_pin_or_readout_missing")
        assessment=fuse_body_evidence(reference,prediction,observation,command_nm)
        state=assessment["state"]
        if state not in STATES:
            raise ValueError("unverified_bodily_evidence")
        hashes={
            label:{
                "primary":digest(canonical(trace["primary"])),
                "pose":digest(canonical(trace["pose"])),
            }
            for label,trace in (("reference",reference),
                                ("prediction",prediction),
                                ("observation",observation))
        }
        payload={
            "schema":"tadash.dual-body-episode.v0.3",
            "session_id":session_id,"event_id":event_id,"ordinal":ordinal,
            "command_nm":float(command_nm),
            "source_sha256":accepted_sha,
            "source_kind":"one_native_MuJoCo_solver_two_virtual_readouts",
            "assessment_state":state,
            "primary_state":assessment["primary_state"],
            "pose_evidence_class":assessment["pose_evidence_class"],
            "causal_origin":"unknown",
            "readout_digests_sha256":hashes,
            "last_native_time_s":observation["primary"]["frames"][-1]["t_s"],
        }
        encoded=canonical(payload)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current,head,_=self._read(session_id)
            previous=self.db.execute("SELECT payload_json,event_hash FROM dual_events "
                                     "WHERE session_id=? AND event_id=?",
                                     (session_id,event_id)).fetchone()
            if previous:
                if previous[0]!=encoded:
                    raise ValueError("conflicting_replay")
                self.db.execute("COMMIT")
                return {"replay":True,"event_hash":previous[1],
                        "state":state}
            if ordinal!=current+1:
                raise ValueError("ordinal_gap_or_replay")
            if current==0:
                self.db.execute("INSERT INTO dual_sessions VALUES (?,?,?)",
                                (session_id,0,GENESIS))
            proof=digest(head+"\n"+encoded)
            self.db.execute("INSERT INTO dual_events VALUES (?,?,?,?,?,?)",
                            (session_id,ordinal,event_id,encoded,head,proof))
            self.db.execute("UPDATE dual_sessions SET last_ordinal=?,head_hash=? "
                            "WHERE session_id=?",(ordinal,proof,session_id))
            self.db.execute("COMMIT")
            return {"replay":False,"event_hash":proof,"state":state}
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def summary(self,session_id):
        snapshot=self.snapshot(session_id)
        events=snapshot["events"]
        counts={state:sum(x["assessment_state"]==state for x in events)
                for state in sorted(STATES)}
        return {
            "kind":"audited_virtual_body_dual_modal_history_v0.3",
            "count":len(events),
            "state_counts":counts,
            "disagreement_or_abstention_fraction":
                (sum(counts[s] for s in UNCERTAIN)/len(events)) if events else None,
            "last_state":events[-1]["assessment_state"] if events else None,
            "last_command_nm":events[-1]["command_nm"] if events else None,
            "verified_head_hash":snapshot["head"],
            "never_infers_consciousness_or_external_cause":True,
        }
