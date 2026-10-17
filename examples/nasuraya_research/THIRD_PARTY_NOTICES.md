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
* `vendor/predvla/model.py` and `vendor/predvla/er.py`: Hiroki Sawada (2026),
  `hiroki-oist/PredVLA`, commit `bba1d038e2fadb8904423cf8f65bb80d70fd17d4`.
  MIT license: `vendor/predvla/LICENSE`.

`vendor/__init__.py`, `vendor/predvla/__init__.py`, the integration adapters,
protocol, and new tests were authored for this repository. The newly fitted
small sensory observer is not an upstream LIBERO checkpoint or a language model.

No code from `Euron-ZC/Humanoid-self-other-distincton-model` is included: its
examined public tree contained a README and static images, not the promised
implementation or a code license.
