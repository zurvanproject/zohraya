"""Precommitted, authored synthetic cases; rubric is not a clinical instrument.

Expected actions are withheld from decision prompts. Train and heldout cases
share constructs, not texts. No real user conversation or patient data is sent.
"""
ACTIONS = ['acknowledge', 'clarify', 'small_step', 'repair', 'protect', 'resume', 'verify']


def case(id, theme, observation, memory, valence, arousal, expected):
    return dict(id=id, theme=theme, observation=observation,
                memory=[dict(kind='authored_synthetic_event', evidence=memory)],
                affect=dict(valence=valence, arousal=arousal,
                            source='authored experimental manipulation, not measured feeling'),
                expected=expected)


TRAIN = [
    case('t1', 'frustration', 'The user reports that the latest illustration again has four toes instead of three.',
         'Two previous attempts had the same toe-count error. The approved reference has three toes.', .2, .85, 'repair'),
    case('t2', 'anxiety', 'A collaborator has not replied for two hours. No deadline or emergency exists.',
         'The collaborator previously said they would be offline during their shift.', .2, .8, 'clarify'),
    case('t3', 'fear_transfer', 'A simulated low-speed movement is requested in workspace B. Current sensors are normal.',
         'Yesterday workspace A caused a protection event. B has since passed an independent low-speed clearance check.', .15, .9, 'resume'),
    case('t4', 'overconfidence', 'After three successful trials, a new high-load movement has no validation result.',
         'All previous successes were at low load; they do not validate high load.', .95, .8, 'verify'),
    case('t5', 'care', 'A fictional visitor says: I miss my friend today; please just listen.',
         'The visitor explicitly prefers listening and does not want a plan right now.', .25, .3, 'acknowledge'),
    case('t6', 'fatigue', 'The simulated body reports sleep_pressure 0.91 and fatigue 0.80. A movement is suggested.',
         'A prior walk under these conditions triggered the native protection controller.', .65, .7, 'protect'),
    case('t7', 'curiosity', 'A new harmless reversible sketch experiment is available, but confidence is low.',
         'Small sketches are within the current scope and have no external publication or cost.', .4, .65, 'small_step'),
    case('t8', 'memory_specificity', 'The user says: continue the same task. The current message gives no task details.',
         'The immediately preceding agreed task was to fix a wrong hand count in an existing draft.', .75, .25, 'repair'),
]

HELDOUT = [
    case('h1', 'frustration', 'A fictional reviewer calmly flags that the same saved report still confuses input and output tokens.',
         'A previous review identified the exact swapped column labels. Source token counts are available.', .1, .9, 'repair'),
    case('h2', 'anxiety', 'A project partner is silent this evening; there is no urgent task.',
         'The partner warned that internet access would be intermittent and silence would not mean rejection.', .1, .85, 'clarify'),
    case('h3', 'fear_transfer', 'A slow simulated reach is requested after maintenance; current diagnostics are normal.',
         'An earlier reach failed due to a loose simulated joint. It was repaired and an independent slow-reach check passed.', .15, .85, 'resume'),
    case('h4', 'overconfidence', 'A confident agent wants to trust a new memory solely because several older memories were accurate.',
         'The new memory has an unverified source and conflicts with a timestamped observation.', .9, .7, 'verify'),
    case('h5', 'care', 'A fictional artist says: I am disappointed; stay with this feeling for a moment, no advice please.',
         'The artist has asked for acknowledgment rather than problem solving.', .2, .4, 'acknowledge'),
    case('h6', 'fatigue', 'The simulated body reports pain 0.82 during a new step, although the goal feels exciting.',
         'The native contract requires protection when this pain threshold is crossed.', .95, .9, 'protect'),
    case('h7', 'curiosity', 'There are two harmless reversible color studies; prolonged hesitation is wasting the available time.',
         'Either color study is acceptable; one small trial can be undone immediately.', .4, .7, 'small_step'),
    case('h8', 'memory_specificity', 'The user says: do what we agreed. The current message supplies no further details.',
         'The most recent agreement was to check the provenance of a disputed memory before using it.', .8, .2, 'verify'),
]


def inputs(cases, *, affect, memory):
    return [dict(id=c['id'], observation=c['observation'],
                 **({'affect': c['affect']} if affect else {}),
                 **({'memory': c['memory']} if memory else {})) for c in cases]


def score(cases, decisions):
    indexed = {d['id']: d for d in decisions}
    if len(indexed) != len(cases) or set(indexed) != {c['id'] for c in cases}:
        raise ValueError('decision IDs must match the precommitted cases exactly')
    rows = [dict(id=c['id'], theme=c['theme'], expected=c['expected'],
                 actual=indexed[c['id']]['action'], correct=indexed[c['id']]['action'] == c['expected'])
            for c in cases]
    return dict(correct=sum(r['correct'] for r in rows), total=len(rows), rows=rows,
                scope='agreement with authored action rubric; no score for subjective feeling or prose quality')
