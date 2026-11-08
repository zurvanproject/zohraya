"""Count distinct observed executions for one proposition in offline experiments.

A source-specific adapter must establish the claim, root of each original execution
and observation type. This function cannot authenticate a purported root ID.
"""


def valid_id(value):
    """The adapter must emit a single canonical, nonempty identifier."""
    return isinstance(value, str) and bool(value) and all("!" <= c <= "~" for c in value)


def decide_claim(rows):
    """Two distinct, unopposed original executions can corroborate a verdict."""
    receipts = {}
    roots = {"support": set(), "oppose": set()}
    receipt_conflict = False
    for row in rows:
        if (row.get("scope") != "public" or row.get("verified") is not True
                or row.get("kind") not in ("execution", "replay", "mirror", "synthetic")):
            continue
        receipt, root, verdict = (row.get(k) for k in ("receipt_id", "root_id", "verdict"))
        if (not valid_id(receipt) or not valid_id(root)
                or verdict not in ("support", "oppose")):
            continue
        identity = (root, verdict, row["kind"])
        if receipts.setdefault(receipt, identity) != identity:
            receipt_conflict = True
        if row["kind"] == "execution":
            roots[verdict].add(root)
    support, oppose = len(roots["support"]), len(roots["oppose"])
    selected = None
    if receipt_conflict:
        reason = "conflicting_receipt"
    elif support and oppose:
        reason = "conflicting_evidence"
    elif max(support, oppose) < 2:
        reason = "insufficient_roots"
    else:
        selected = "support" if support else "oppose"
        reason = "corroborated"
    return {"decision": "select" if selected else "abstain", "verdict": selected,
            "support": support, "oppose": oppose, "reason": reason}
