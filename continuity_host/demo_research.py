"""Reproduce four cold-process lab rounds in a NEW local output directory."""
import argparse
import json
import os
from pathlib import Path

from continuity_host import research_lab as lab
from continuity_host.research_host import worker


def publish(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        stream.write(lab.encode(value)+'\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def demonstrate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    checkpoint = output/'memory.json'
    publish(checkpoint, lab.initial())
    rounds = []
    for index in range(1, 5):
        # Every experiment starts in a fresh interpreter, from the disk checkpoint.
        memory = json.loads(checkpoint.read_text(encoding='utf-8'))
        result = worker(memory, 'synthetic_demo_'+str(index))
        lab.validate(result['memory'])
        publish(output/('round_'+str(index)+'.json'), result['receipt'])
        publish(checkpoint, result['memory'])
        trial = result['receipt']['trial']
        rounds.append(dict(round=index, feature=trial['feature'], accepted=trial['accepted'],
            validation_before=trial['holdout']['before']['errors'],
            validation_after=trial['holdout']['after']['errors'], total=288))
    memory = json.loads(checkpoint.read_text(encoding='utf-8'))
    replay = worker(memory, 'synthetic_demo_1')
    complete = worker(memory, 'synthetic_demo_5')
    assert replay['memory'] == memory and complete['memory'] == memory
    assert complete['receipt']['status'] == 'curriculum_complete'
    summary = dict(schema='nasuraya-first-day-demo/1', engine=lab.engine_digest(),
        rounds=rounds, old_request_preserves_latest=True, finite_curriculum_stops=True,
        cold_processes=6, training_cases=192, validation_cases=288,
        checkpoint_sha256=lab.digest(memory), model_api_used=False,
        limitations='Authored synthetic family; reused validation set; no live deployment or generalization claim.')
    publish(output/'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(demonstrate(args.output), indent=2))
