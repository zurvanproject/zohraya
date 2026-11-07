# باغ نور | Tadash Fox Playground v0.1

A small **independent, offline play sandbox** for the fictional character Nasuraya, inspired by Tadash's visual form (horns, copper fur, three-toed paws and blue fox totem). Persian UI; works on mobile browsers without packages, API keys or network calls.

## Run / play

Open `index.html` in a browser, or serve the directory locally with `python3 -m http.server 8000`. Choose **تماشای بازی** to watch the deterministic local navigation policy collect five blue sparks; choose **کنترل دستی** for manual arrow-key/touch controls. Reset makes a different seeded map. Reachable spark placement is ensured.

## Validation

Run `node test_playground.cjs` (Node 18+). The test checks 30 seeded maps and confirms the policy can collect all five sparks on each map within 160 steps. This checks **task completion only**, not learning, embodiment, self-awareness or subjective enjoyment.

## System boundary

- Contains no API calls, scheduling, cloud compute, filesystem or control interfaces to actual Tadash body drivers.
- A **demo**, not installed in/connected to the continuous Tadash runtime; no autonomous process is running when the page is closed.
- `score` and `spark` are **numerical game rewards**; they do not prove experience of pleasure or emotions.
- No permissions are requested, no network calls or persistent storage, no third-party dependencies, no untrusted code loaded.
- Kept in `examples/` deliberately. Integration into `runtimes/tadash_body` requires a separate safety + compatibility review.

## Suggested follow-on

A read-only replay/adapter could map game events to `observe`, `act`, and `outcome` messages with checksums, then compare goal-directed and random policies without touching the embodiment safety gates.