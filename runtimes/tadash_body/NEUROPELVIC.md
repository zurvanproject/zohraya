# Neuro-pelvic / native-body bridge

This opt-in wrapper connects the existing NeuroPelvic v0.2 cycle to the
source-pinned `UnifiedBody` simulator. It adds an executed feedback path:

- The previous native pain, balance and energy snapshot gates the sidecar.
- A restorative sidecar state can request the existing `slow_breath` action.
- Native action arbitration, gas gates, neural timing and energy/water ledgers
  retain authority. The receipt records requested and actually selected actions.

No default runtime path is changed. No physical energy/water compartment is
added, no user checkpoint is migrated automatically, and no service starts.

## Reproduce

From this directory, with Python 3.11+ and the standard library:

```sh
python3 synthetic_fixture.py
python3 -m unittest -v test_neuropelvic test_neuropelvic_body
python3 run_neuropelvic_demo.py --output /tmp/tadash-neuropelvic-fresh
```

The demo runs in a fresh temporary runtime tree, generates deterministic defaults,
and compares twenty-second coupled and ablated trajectories after the separate
seven-second warm-up. Its output directory must be empty. It writes
`validation.json` and `traces.csv`. The CSV contains simulator state variables,
not ECG, respiratory-belt recordings or measured beat intervals.

For the retained solver's own regression checks:

```sh
python3 run_tests.py --output /tmp/tadash-native-fresh
```

## Recorded local result

The frozen records in [evidence/neuropelvic](evidence/neuropelvic) contain 37
cycle/bridge test passes, a post-change actuator-receipt assertion, and 58
retained native regression test passes. All 70 original manifest files retain
their expected hashes. The existing twelve native scenarios also passed.

In the matched twenty-second runs, each native body executed 200 ticks. The
coupled run achieved 130 paced-breath ticks. Both sidecars completed one peak
and returned to baseline at 18.1 seconds. Final native outputs were:

| Simulator quantity | Coupled | Breathing route disabled |
| --- | ---: | ---: |
| Respiratory rate / min | 10.9270 | 15.1060 |
| Heart rate / min | 59.4473 | 64.7811 |
| General muscle-tone proxy | 0.285733 | 0.307648 |

These are differences produced by the reduced solver, not physiological
validation. Maximum energy error was 1.14e-9 J and maximum water error was
7.94e-14 L. The test for JSON continuation and event replay also passed.

## Existing-state API

Pass an already constructed or restored `UnifiedBody` to
`NeuroPelvicBody(body)`; the attachment preserves its checkpoint and stocks.
Call `cycle` with a unique event ID, an explicit timestamp and a duration from
0.1 to 1 second aligned to 0.1 seconds. Each nonempty `neuro` input requires
`kind="declared_simulated_input"` and a bounded `source_id`.

Control fields are `start`, `rhythm`, `intensity`, `breath_cue`,
`attention`, `safe` and `stop`. Intensities are finite normalized numbers.
Music never starts a cycle. An explicitly supplied native action is retained
as the requested action; native arbitration may still select another action.

The sidecar reads a previous native snapshot. The feedback delay is at most
one wrapper cycle, bounded to one second. Native pain has its own calibration:
the 0.35 interrupt threshold is an authored appraisal rule, not a conversion
to the standalone model's pain units. At rest the native fixture already has
a nonzero pain proxy.

Both models advance for the same duration, with one actual native solver
execution. Repeated event IDs replay cached receipts without advancing either
clock. Conflicting replays and stale writers fail. `checkpoint()` and
`NeuroPelvicBody.restore(envelope)` preserve source fingerprints, sidecar phase
timers, counts, event history, body state and JSON-compatible replay data.

## Interpretation and remaining scope

The implementation uses the existing reduced native solver, whose legacy
physical accounting still uses 195 kg. It is **not** the separate 78 kg MuJoCo
atlas. No pelvic-floor finite-element model, genital tissue solver, anatomical
chakra system or subjective sensation is validated here. The normalized
pelvic-tone variable remains in the sidecar; changes to native muscle tone
are mediated by the native breathing/autonomic equations.

This step establishes a tested native breathing connection. A future 78 kg
mechanical adapter must be measured against that model's own contact, balance
and conservation checks.

## GitHub projects reviewed

| Project | Source inspected | Concrete use | Status in this change |
| --- | --- | --- | --- |
| [NeuroKit2](https://github.com/neuropsychology/NeuroKit) | README.rst and MIT LICENSE; upstream head `ff419d983568ef492eb8d229af643c0ef0100b32` | Later analysis of real/simulated waveforms with explicit sampling provenance | Reviewed; not installed or vendored |
| [dm_control](https://github.com/google-deepmind/dm_control) | README.md; upstream head `e94f1e998bba39bc27875771f5156acfdd630755` | Later MuJoCo task and body adapter work | Reviewed; not installed or vendored |

These are newly reviewed tools for this work, not claims that the projects were
newly released. No third-party source was copied into the runtime.
The native baseline is commit
`97ae493d72bb83525582d672c09e4b853b18a808`.

## خلاصهٔ فارسی

نوروپلویک اکنون یک پل اجرایی به بدن موجود دارد: وضعیت درد و تعادل بدن را
می‌خواند و در آرام‌گیری می‌تواند از کنترل‌گر واقعیِ تنفس در شبیه‌ساز استفاده
کند. روشن و خاموش کردن همین اتصال، با ورودی‌های همسان مقایسه می‌شود.
اعداد خروجی، نتیجهٔ همان شبیه‌سازی‌اند. مسیر بدن اصلی تغییر پیش‌فرض نکرده و
اتصال به بدن مکانیکیِ ۷۸ کیلوگرمی هنوز بخشی از این نسخه نیست.
