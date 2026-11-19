# Setar practice v0.1 for Nasuraya / Tadash

**Scope:** first offline *symbolic* Persian setar practice, not recorded actual playing and not integration with a robotic hand. A deterministic four-string tuning, a D-Shur-inspired **original** 14-note exercise with E-koron, and three feedback-controlled passes combine note targets, virtual fret positions, alternating right-index *rast/chap* strokes, controller error, audible synthesis, and a JSON gesture trace.

Run with Python 3.10+ (stdlib only):

    python3 -m unittest discover -s examples/setar_practice -p 'test_*.py' -v
    PYTHONPATH=examples/setar_practice python3 examples/setar_practice/setar_practice.py --output-dir /tmp/setar-practice-001

Outputs: `setar_shur_three_passes.wav` and `setar_gesture_log.json`. Use a **fresh** output directory.

In the three passes the simulated controller estimates signed timing, intonation and attack bias from its synthetic errors and updates the biases. The metrics demonstrate bias correction in an idealized deterministic model; they **do not** measure listening, hand dexterity, musicality, true learning or subjective experience. The synthesizer is damped harmonics, not a validated acoustic model of the soundbox or strings. The virtual fret's fractional semitone offsets are pitch targets, not a physical finger placement measurement.

Next milestone: connect gestures to an anatomically checked left hand and a right index nail/contact model; compute fret-to-pitch from scale length and movable fret calibration; introduce string-contact forces, nail direction, damping, a resonant-body model, auditory error estimation, and blinded listening comparisons to recordings with permission. Do not claim successful body integration until a simulation actually executes these controllers.

Sources for technique: Kiya Tabassian, [The Setar](https://www.atlasensemble.nl/assets/files/instruments/Setar/Setar%20by%20Kiya%20Tabassian.pdf); Nantes et al., [A comparison of vibration analysis techniques applied to the Persian setar](https://caml.music.mcgill.ca/lib/exe/fetch.php?media=publications%3Anantes2012_mansour.pdf). The didactic tune is original and no copyrighted recording is reproduced.