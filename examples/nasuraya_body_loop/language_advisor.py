"""Lazy opt-in: legacy body/API commands never need ML dependencies."""
KEY='nasuraya-language-advisor/2'


def host_type(loop):
    if loop.engine.db.execute('SELECT 1 FROM meta WHERE key=?',(KEY,)).fetchone():
        from examples.nasuraya_language_choice.advisor import AdvisedBodyAPIHost
        return AdvisedBodyAPIHost
    from .api_host import BodyAPIHost
    return BodyAPIHost
