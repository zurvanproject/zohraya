# Third-party subsets

The files listed in `upstream-lock.json` are redistributed **unmodified**, under
their original licenses. Their Git blob IDs and SHA256 values are checked before
use. No external model weights, datasets, simulator binaries, full vendor
packages or API credentials are included. New adapters retain a separate
namespace and do not imply endorsement by any upstream author.

* `vendor/battery_probe.py`: Jon-Paul Cacioli's
  `synthiumjp/metacognitive-monitoring-battery`, `analysis/probe_analysis.py`,
  commit `2f83d0fa506e7af2b72ca191b65ce42e07c9e185`.
  MIT license: `vendor/licenses/battery-MIT.txt`.
* `vendor/roborsi_trajectory.py`: The HEART Authors,
  `OpenSenseNova/SenseNova-RoboRSI`, `roborsi/evaluation/trajectory.py`,
  commit `f7542dfea2a852dbd151da86a2e9fc475d3257fd`.
  Apache-2.0 license: `vendor/licenses/roborsi-Apache-2.0.txt`.
  Original copyright and license header is retained.
* `vendor/mjlab_math.py`: The Isaac Lab Project Developers (2022–2025), with
  modifications documented in the original header by the mjlab developers.
  Source: `mujocolab/mjlab`, `src/mjlab/utils/lab_api/math.py`, commit
  `45b1e263ec1c3c0d2c3211b458135d80bb7030df`.
  This file is BSD-3-Clause, **not** mjlab's general Apache-2.0 license.
  See `vendor/licenses/IsaacLab-BSD-3-Clause.txt`. The upstream Apache license
  is also preserved in `vendor/licenses/mjlab-Apache-2.0.txt` for context.

`vendor/__init__.py`, the adapters, extracted native snapshot, and tests are
repository integration code. PredVLA, training, fitted weights and the full
quantitative pilot are excluded from this minimal observer.

The BSD notice is retained byte-for-byte from PR #44 and additionally pinned
by `SUPPLEMENTAL_LICENSE_SHA256` in integrity.py; it is not represented as a
separately retrieved upstream Git blob.
