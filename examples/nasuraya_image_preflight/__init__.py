"""DIOS: auditable local image-request preflight, not a provider safety model."""
from .engine import evaluate, RULE_VERSION
from .store import Store
__all__ = ["evaluate", "Store", "RULE_VERSION"]
