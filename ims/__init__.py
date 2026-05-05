"""
PAM Integrated Management System (IMS).

Mirrors the architecture from He et al., CIBDA 2024 (Figure 4):
    QueryInterface -> Unwrapper / TaskAnalyzer
                   -> FormatOptimizer / PlanOptimizer
                   -> MetadataManager
                   -> SubqueryDistributor & Accumulator

Today (Day 1): skeletons + a minimal working pipeline so the FastAPI layer
can route every request through IMS instead of calling query() directly.
Days 2-4 will fill in real query parsing, plan optimization, parallel
execution, and metadata-driven file pruning.
"""
from .query_interface import QueryInterface
from .metadata_manager import MetadataManager

__all__ = ["QueryInterface", "MetadataManager"]
