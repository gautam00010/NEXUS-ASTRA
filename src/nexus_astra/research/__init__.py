"""Institutional LFT Research Module.

Exports:
- InstitutionalLFTResearchEngine: Complete 6-stage quant research pipeline.
- run_research_demonstration: Instant demonstration execution.
"""

from __future__ import annotations
from nexus_astra.research.lft_template import InstitutionalLFTResearchEngine, run_research_demonstration

__all__ = ["InstitutionalLFTResearchEngine", "run_research_demonstration"]
