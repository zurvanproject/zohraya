"""Reproducible synthetic cold-process memory/dialogue continuity check."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .sourced_memory import export_archive


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    archive = output / 'synthetic-memory.json'
    sources = [dict(id='synthetic-note', source_kind='authored_continuity_note',
                    locator='fixture://memory-session-demo/note', library_file_id=None,
                    file_id=None, file_name='synthetic-note.txt', version=1,
                    text='یادداشت ساختگی: رنگ کلاه سبز است.\r\n'),
               dict(id='synthetic-user', source_kind='verbatim_user_message',
                    locator='fixture://memory-session-demo/message', library_file_id=None,
                    file_id=None, file_name='synthetic-message.txt', version=None,
                    text='پیام ساختگی: رنگ کلاه را به یاد بیاور.\n')]
    pin = export_archive(sources, archive)['archive_sha256']
    original_bytes_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    session = output / 'session'

    def call(command, *args):
        result = subprocess.run([sys.executable, '-m', 'nasuraya.memory_session_cli', command,
                                 '--session-dir', str(session), '--expected-sha256', pin,
                                 *map(str, args)], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    call('init', '--archive', archive, '--max-actions', '1')
    # These are explicit caller-authored engineering appraisals, not emotions
    # inferred from retrieved content.
    checks = dict(relevance=1., goal_congruence=.8, controllability=.7, novelty=.8,
                  certainty=1., progress=0., loss=0., threat=0., norm_conflict=0.)
    message = dict(id='synthetic-one', text='رنگ کلاه', intent='observe',
                   appraisal=checks, duration_s=.1)
    payload = output / 'synthetic-message.json'
    payload.write_text(json.dumps(message, ensure_ascii=False) + '\n', encoding='utf-8')
    first = call('message', '--message', payload)
    before = call('status')
    # The session owns a pinned private snapshot: loss of the source location
    # does not erase recall. Restore the synthetic input after the check.
    detached = output / 'detached-synthetic-memory.json'
    archive.rename(detached)
    try:
        replay = call('message', '--message', payload)
        trace = call('trace', '--message-id', message['id'])
        after = call('status')
    finally:
        detached.rename(archive)
    report = dict(schema='nasuraya.memory-session-demo/1', source='synthetic only',
                  fresh_process_per_command=True,
                  archive_bytes_unchanged=hashlib.sha256(archive.read_bytes()).hexdigest() == original_bytes_sha,
                  retrieved_sources=len(first['memory_context']['hits']),
                  retrieval_equal_after_source_disconnect=first['memory_context'] == replay['memory_context'],
                  trace_context_equal=trace['memory_context'] == first['memory_context'],
                  first_call_body_cycles=first['this_call_body_cycles'],
                  replay_body_cycles=replay['this_call_body_cycles'],
                  native_and_memory_status_equal=before == after,
                  completed_native_cycles=after['native']['body']['completed_cycles'],
                  native_episode_count=len(after['native']['experience']['episodes']),
                  source_kinds=sorted(h['source']['source_kind'] for h in first['memory_context']['hits']),
                  historical_hits_unverified=all(not h['verified_fact'] and not h['native_outcome_recorded']
                                                 for h in first['memory_context']['hits']),
                  external_api_calls=0, automatic_chatgpt_listener=False)
    if not (report['archive_bytes_unchanged'] and report['retrieval_equal_after_source_disconnect']
            and report['trace_context_equal'] and report['native_and_memory_status_equal']
            and report['historical_hits_unverified'] and report['retrieved_sources'] == 2
            and report['first_call_body_cycles'] == report['completed_native_cycles'] ==
            report['native_episode_count'] == 1 and report['replay_body_cycles'] == 0):
        raise RuntimeError('synthetic memory-session continuity contract failed')
    (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
