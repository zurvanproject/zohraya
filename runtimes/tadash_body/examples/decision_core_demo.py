"""Run from repository root: python examples/decision_core_demo.py."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from decision_core import Action, Consequence, DecisionCore


def option(name, *, harm=0.05, benefit=0.2, cost=0.1, compassion=0.8, confidence=1.0):
    return Action(name, (Consequence(1.0, harm, benefit, cost, confidence),),
                  respect=0.9, honesty=0.9, balance=0.8, dignity=0.9,
                  compassion=compassion, disharmony=0.1)


def scenarios():
    return {
        'benefit_vs_harm': [option('exploit', harm=0.9, benefit=1.0), option('fair_gain', benefit=0.4)],
        'compassion_vs_cost': [option('help', cost=0.7, compassion=1.0), option('ignore', cost=0.0, compassion=0.1)],
        'incomplete_information': [option('act_now', benefit=1.0, confidence=0.2), option('gather_evidence', benefit=0.1, cost=0.2)],
    }


if __name__ == '__main__':
    print(json.dumps({name: DecisionCore().decide(actions).to_dict()
                      for name, actions in scenarios().items()}, indent=2, ensure_ascii=False))
