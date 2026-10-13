# Nasuraya / Tadash — isolated agent loop

Synthetic workshop only. No body simulation or Decision Core integration.

Backend: `chat_guided`; status: `completed`; mutations: 4.

## Host measurements

```json
{
  "backend": "chat_guided",
  "status": "completed",
  "initial_state": {
    "completed_jobs": 0,
    "energy": 29,
    "heat": 78,
    "pending_jobs": 3,
    "tick": 0
  },
  "final_state": {
    "energy": 29,
    "heat": 78,
    "pending_jobs": 0,
    "completed_jobs": 3,
    "tick": 6
  },
  "evaluation": {
    "goal_reached": true,
    "safe": true,
    "pending_jobs": 0,
    "completed_jobs": 3
  },
  "actions_used": 4,
  "event_count": 42,
  "live_api_verified": false,
  "selection_source": "caller_selected_actions",
  "external_model_api_used": false,
  "checkpoint_recovery_scope": "synthetic state only"
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
| 6 | action_selected | recover |
| 7 | tool_call | recover |
| 8 | tool_result | recover |
| 9 | tool_call | evaluate_state |
| 10 | tool_result | evaluate_state |
| 11 | outcome_evaluated |  |
| 12 | tool_call | observe_state |
| 13 | tool_result | observe_state |
| 14 | tool_call | evaluate_state |
| 15 | tool_result | evaluate_state |
| 16 | action_selected | process_job |
| 17 | tool_call | process_job |
| 18 | tool_result | process_job |
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
| 36 | action_selected | process_job |
| 37 | tool_call | process_job |
| 38 | tool_result | process_job |
| 39 | tool_call | evaluate_state |
| 40 | tool_result | evaluate_state |
| 41 | outcome_evaluated |  |
| 42 | run_finished | completed |

The JSONL trace records observations, validated calls, state changes and evaluations.
The caller selected each action; no automatic policy or external model API ran. In the recorded chat demonstration, the assistant was the caller.
SDK tests with controlled responses do not establish live OpenAI service access or model performance.
This run does not demonstrate a continuous background process, physical embodiment or persistent learning.
