"""Explicit deterministic materialization; review/version changes before committing."""
import json
from .traits import HERE, baseline, build_contract, build_schema


def generate():
    contract = build_contract()
    for name, value in [('contract-v0.1.json', contract),
                        ('genotype-v0.1.schema.json', build_schema(contract))]:
        (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    (HERE / 'baseline-v0.1.json').write_text(json.dumps(baseline(), indent=2) + '\n')


if __name__ == '__main__':
    generate()
