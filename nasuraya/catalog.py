"""Explicit dispatch catalogue; imports never initialize sessions or services."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Public command -> existing entry point, dependency profile, description.
CAPABILITIES = {
    'body': ('examples.nasuraya_body_loop', 'core', 'Native body, sleep, care, wakeups, adaptive memory and admission control'),
    'dialogue': ('examples.nasuraya_affect.dialogue_cli', 'core', 'Message, affect, native body execution and durable feedback'),
    'articulated': ('examples.nasuraya_affect.articulated_cli', 'mechanics', '85 kg articulated dialogue with persistent mechanical checkpoints'),
    'affect': ('examples.nasuraya_affect', 'core', 'Persistent appraisal and bounded action planning'),
    'aesthetics': ('examples.nasuraya_aesthetics', 'core', 'Source-attributed aesthetic appraisal and body feedback'),
    'agent': ('examples.nasuraya_agent_loop', 'sdk', 'Tool loop and explicit API transport'),
    'self-model': ('examples.nasuraya_self_model.session_cli', 'core', 'Persistent bounded goals and experiential control'),
    'self-observe': ('nasuraya.self_observe', 'core', 'Read-only audited self-model of an existing native body checkpoint'),
    'genome': ('examples.nasuraya_genome.history', 'core', 'Replayable proposal ancestry; no body application'),
    'genome-traits': ('examples.nasuraya_genome.traits', 'core', '48-chromosome genotype expression'),
    'genome-design': ('examples.nasuraya_genome.run_design_cycle', 'core', 'Source-bound structural proposal comparisons'),
    'genome-values': ('examples.nasuraya_genome.design_value_review', 'core', 'Independent functional and user aesthetic review'),
    'research': ('examples.nasuraya_research.control', 'core', 'Native observations, bounded control and confidence'),
    'research-study': ('examples.nasuraya_research.evaluate', 'tensor', 'Pinned research models and offline evaluation'),
    'spiral': ('examples.nasuraya_star_motion.evaluate_spiral', 'core', 'Bounded star and spiral motion'),
    'running': ('examples.nasuraya_research.evaluate_running', 'mechanics', 'Experimental spring-mass running feedback; separate from articulated walking'),
    'dream': ('examples.nasuraya_research.dream_ten', 'core', 'Bounded offline policy search with held-out evaluation'),
    'dream-native': ('examples.nasuraya_research.dream_ten_native', 'core', 'Native validation retaining negative results'),
    'anatomy': ('examples.nasuraya_anatomy_audit.audit', 'core', 'Anatomy provenance and motion audit'),
    'host': ('continuity_host.host', 'core', 'Explicit bounded GitHub host; requires existing authorization state'),
    'research-host': ('continuity_host.research_host', 'core', 'Current daily research host; preserves live authorization, memory and model budgets'),
    'research-day': ('continuity_host.demo_research', 'core', 'Offline synthetic memory experiments with cold-process continuation; no model calls'),
    'tissues': ('examples.nasuraya_tissue_lab.run_lab', 'core', 'Regional body tissue observations'),
    'guard': ('examples.nasuraya_security.guarded_cycle', 'core', 'Explicit local integrity, decision and experience loop'),
    'causal-study': ('examples.nasuraya_causal_probe.run', 'core', 'Frozen workspace-access mechanism experiments'),
    'language-train': ('examples.nasuraya_language_adapter.train', 'tensor', 'Local adapter weight experiments'),
    'language-body': ('examples.nasuraya_language_body.experiment', 'tensor', 'Body-informed local language experiment'),
    'language-internals': ('examples.nasuraya_lm_internals.probe', 'tensor', 'Local transformer attention probes'),
    'continuity': ('nasuraya_continuity_kit.cli', 'core', 'Durable offline jobs and bounded local reports'),
    'fund': ('project_fund.planner', 'core', 'Project funding proposals; no payment execution'),
    'audit-service': ('services.replay_audit.audit', 'core', 'Offline service pilot for replay and budget audits'),
}


def rows():
    return [dict(id=key, module=value[0], profile=value[1], description=value[2])
            for key, value in CAPABILITIES.items()]


def validate():
    for row in rows():
        path = ROOT.joinpath(*row['module'].split('.'))
        if not (path.with_suffix('.py').is_file() or (path / '__main__.py').is_file()):
            raise ValueError('missing entry point: ' + row['module'])
    return rows()
