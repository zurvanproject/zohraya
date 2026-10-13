# Nasuraya / Tadash — isolated agent loop

Synthetic workshop only. No body simulation or Decision Core integration.

Backend: `offline`; status: `completed`; mutations: 5.

## Host measurements

```json
{
  "backend": "offline",
  "status": "completed",
  "initial_state": {
    "energy": 45,
    "heat": 50,
    "pending_jobs": 3,
    "completed_jobs": 0,
    "tick": 0
  },
  "final_state": {
    "energy": 25,
    "heat": 70,
    "pending_jobs": 0,
    "completed_jobs": 3,
    "tick": 5
  },
  "evaluation": {
    "goal_reached": true,
    "safe": true,
    "pending_jobs": 0,
    "completed_jobs": 3
  },
  "actions_used": 5,
  "event_count": 52,
  "live_api_verified": false
}
```

## Event index

| Seq | Event | Detail |
| --- | --- | --- |
| 1 | run_started |  |
| 2 | tool_call | observe_state |
| 3 | tool_result | observe_state |
| 4 | tool_call | evaluate_state |
| 5 | tool_result | evaluate_state |
| 6 | action_selected | process_job |
| 7 | tool_call | process_job |
| 8 | tool_result | process_job |
| 9 | tool_call | evaluate_state |
| 10 | tool_result | evaluate_state |
| 11 | outcome_evaluated |  |
| 12 | tool_call | observe_state |
| 13 | tool_result | observe_state |
| 14 | tool_call | evaluate_state |
| 15 | tool_result | evaluate_state |
| 16 | action_selected | recover |
| 17 | tool_call | recover |
| 18 | tool_result | recover |
| 19 | tool_call | evaluate_state |
| 20 | tool_result | evaluate_state |
| 21 | outcome_evaluated |  |
| 22 | tool_call | observe_state |
| 23 | tool_result | observe_state |
| 24 | tool_call | evaluate_state |
| 25 | tool_result | evaluate_state |
| 26 | action_selected | process_job |
| 27 | tool_call | process_job |
| 28 | tool_result | process_job |
| 29 | tool_call | evaluate_state |
| 30 | tool_result | evaluate_state |
| 31 | outcome_evaluated |  |
| 32 | tool_call | observe_state |
| 33 | tool_result | observe_state |
| 34 | tool_call | evaluate_state |
| 35 | tool_result | evaluate_state |
| 36 | action_selected | recover |
| 37 | tool_call | recover |
| 38 | tool_result | recover |
| 39 | tool_call | evaluate_state |
| 40 | tool_result | evaluate_state |
| 41 | outcome_evaluated |  |
| 42 | tool_call | observe_state |
| 43 | tool_result | observe_state |
| 44 | tool_call | evaluate_state |
| 45 | tool_result | evaluate_state |
| 46 | action_selected | process_job |
| 47 | tool_call | process_job |
| 48 | tool_result | process_job |
| 49 | tool_call | evaluate_state |
| 50 | tool_result | evaluate_state |
| 51 | outcome_evaluated |  |
| 52 | run_finished | completed |

The JSONL trace records observations, validated calls, state changes and evaluations.
Offline selection uses a deterministic fixture policy. API contract tests use a fake client; they do not establish live service access or model performance.
No continuous background process, consciousness claim, physical embodiment, or persistent learning is demonstrated.
