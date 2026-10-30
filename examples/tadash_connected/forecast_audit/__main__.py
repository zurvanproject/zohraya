"""Run the offline forecast experiment without feeding predictions back to the body."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ..__main__ import DREAMER_REV, HERE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="new results directory")
    parser.add_argument("--dream-python", required=True, type=Path)
    parser.add_argument("--dream-source", required=True, type=Path)
    parser.add_argument("--traces", type=Path, help="reuse complete cold-recovered audit traces")
    args = parser.parse_args(argv)
    output, python = args.output_dir.absolute(), args.dream_python.absolute()
    source = args.dream_source.resolve()
    if output.exists() or output.is_symlink():
        parser.error("output already exists")
    if subprocess.check_output(["git", "-C", source, "rev-parse", "HEAD"], text=True).strip() != DREAMER_REV:
        parser.error("use Dreamer checkout " + DREAMER_REV)
    env = dict(os.environ, JAX_PLATFORMS="cpu", TERM="xterm", OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    env.pop("OPENAI_API_KEY", None)
    module = "examples.tadash_connected.forecast_audit."
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        result = Path(temp) / "result"
        result.mkdir()
        traces = args.traces.resolve() if args.traces else result / "traces"
        if not args.traces:
            subprocess.run([sys.executable, "-m", module + "collect", traces],
                           cwd=HERE.parents[1], env=env, check=True)
        env["PYTHONPATH"] = str(source)
        for arguments in (["fit", traces, result / "fits"],
                          ["score", traces, result / "scores", "--fits", result / "fits"]):
            subprocess.run([python, "-m", module + "experiment", *arguments],
                           cwd=HERE.parents[1], env=env, check=True)
        result.rename(output)
    print(output / "scores" / "scores.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
