"""Print a reproducible LOCAL report, without requesting API/keys/network."""
from . import indicators, mechanisms, probes
from .evidence import prior_forecasting_receipt


def main():
    report = indicators.audit(probes.probes())
    lab = mechanisms.PrototypeCycle()
    report["example_cycle"] = lab.step(
        visual=0.6, audio=0.7, danger=0.2, goal=0.7,
        noise=0.2, sensory=0.8,
    )
    report["related_prior_project_evidence"] = prior_forecasting_receipt()
    report["api_used"] = False
    report["canonical_body_changed"] = False
    print(indicators.canonical(report))


if __name__ == "__main__":
    main()
