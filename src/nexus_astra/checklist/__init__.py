"""Institutional Pre-Trade Checklist Module.

Exports:
- evaluate_institutional_checklist: 5-question strict binary filter for trade execution.
"""

from __future__ import annotations
from nexus_astra.checklist.institutional_checklist import evaluate_institutional_checklist

__all__ = ["evaluate_institutional_checklist"]
