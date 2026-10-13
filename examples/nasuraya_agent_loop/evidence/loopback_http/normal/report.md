# Nasuraya / Tadash — isolated agent loop

Synthetic workshop only. No body simulation or Decision Core integration.

Backend: `agents_api`; status: `completed`; mutations: 5.

## Host measurements

```json
{
  "backend": "agents_api",
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
  "event_count": 95,
  "live_api_verified": false,
  "api_transport": "loopback_http",
  "session_id": "sess-loopback",
  "cleanup_status": "deleted",
  "selection_source": "scripted_fixture",
  "http_requests": 19,
  "external_model_api_used": false
}
```

## Event index

| Seq | Event | Detail |
| --- | --- | --- |
| 1 | run_started |  |
| 2 | api_session_created |  |
| 3 | api_event |  |
| 4 | api_call_pending |  |
| 5 | tool_call | observe_state |
| 6 | tool_result | observe_state |
| 7 | api_result_submitted |  |
| 8 | api_event |  |
| 9 | api_call_pending |  |
| 10 | tool_call | process_job |
| 11 | tool_result | process_job |
| 12 | tool_call | evaluate_state |
| 13 | tool_result | evaluate_state |
| 14 | outcome_evaluated |  |
| 15 | api_result_submitted |  |
| 16 | api_event |  |
| 17 | api_call_pending |  |
| 18 | tool_call | evaluate_state |
| 19 | tool_result | evaluate_state |
| 20 | api_result_submitted |  |
| 21 | api_event |  |
| 22 | api_call_pending |  |
| 23 | tool_call | observe_state |
| 24 | tool_result | observe_state |
| 25 | api_result_submitted |  |
| 26 | api_event |  |
| 27 | api_call_pending |  |
| 28 | tool_call | recover |
| 29 | tool_result | recover |
| 30 | tool_call | evaluate_state |
| 31 | tool_result | evaluate_state |
| 32 | outcome_evaluated |  |
| 33 | api_result_submitted |  |
| 34 | api_event |  |
| 35 | api_call_pending |  |
| 36 | tool_call | evaluate_state |
| 37 | tool_result | evaluate_state |
| 38 | api_result_submitted |  |
| 39 | api_event |  |
| 40 | api_call_pending |  |
| 41 | tool_call | observe_state |
| 42 | tool_result | observe_state |
| 43 | api_result_submitted |  |
| 44 | api_event |  |
| 45 | api_call_pending |  |
| 46 | tool_call | process_job |
| 47 | tool_result | process_job |
| 48 | tool_call | evaluate_state |
| 49 | tool_result | evaluate_state |
| 50 | outcome_evaluated |  |
| 51 | api_result_submitted |  |
| 52 | api_event |  |
| 53 | api_call_pending |  |
| 54 | tool_call | evaluate_state |
| 55 | tool_result | evaluate_state |
| 56 | api_result_submitted |  |
| 57 | api_event |  |
| 58 | api_call_pending |  |
| 59 | tool_call | observe_state |
| 60 | tool_result | observe_state |
| 61 | api_result_submitted |  |
| 62 | api_event |  |
| 63 | api_call_pending |  |
| 64 | tool_call | recover |
| 65 | tool_result | recover |
| 66 | tool_call | evaluate_state |
| 67 | tool_result | evaluate_state |
| 68 | outcome_evaluated |  |
| 69 | api_result_submitted |  |
| 70 | api_event |  |
| 71 | api_call_pending |  |
| 72 | tool_call | evaluate_state |
| 73 | tool_result | evaluate_state |
| 74 | api_result_submitted |  |
| 75 | api_event |  |
| 76 | api_call_pending |  |
| 77 | tool_call | observe_state |
| 78 | tool_result | observe_state |
| 79 | api_result_submitted |  |
| 80 | api_event |  |
| 81 | api_call_pending |  |
| 82 | tool_call | process_job |
| 83 | tool_result | process_job |
| 84 | tool_call | evaluate_state |
| 85 | tool_result | evaluate_state |
| 86 | outcome_evaluated |  |
| 87 | api_result_submitted |  |
| 88 | api_event |  |
| 89 | api_call_pending |  |
| 90 | tool_call | evaluate_state |
| 91 | tool_result | evaluate_state |
| 92 | api_result_submitted |  |
| 93 | api_event |  |
| 94 | api_session_deleted |  |
| 95 | run_finished | completed |

The JSONL trace records observations, validated calls, state changes and evaluations.
Selection source and API verification scope are recorded in the summary.
SDK tests with controlled responses do not establish live OpenAI service access or model performance.
This run does not demonstrate a continuous background process, physical embodiment or persistent learning.
