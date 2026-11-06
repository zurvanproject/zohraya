# NASURAYA Offline Trace Audit

Result: **review_required**
Events: 5
Input SHA-256: `961e245fe7d9c2a3337b5896a7f842202a31a53660d49305575619425d7bd7f2`

Reported cost: 110 minor units USD; budget: 100.

caller-reported incremental amounts; not verified billing

| Finding | Line | Related line | Suggested action |
| --- | ---: | ---: | --- |
| request_reused | 4 | 1 | Bind request IDs to one attempt; reconcile before retrying. |
| budget_exceeded | 5 |  | Enforce a budget before admission, with reserved capacity for in-flight work. |
| duplicate_effect | 5 | 2 | Reconcile the external effect using its idempotency key before retrying. |
| unresolved_run | 4 |  | Investigate the worker and effect outcome before retrying. |

## Limitations

- Trace-only consistency review; no code execution, crash injection or external verification.
- Missing starts/ends may reflect a partial export rather than a runtime defect.
- Repeated effect records are candidates for investigation, not proof of repeated payment.
- Input must use one currency and incremental costs, not cumulative billing totals.
- No findings does not prove safety, exactly-once execution or complete logging.
