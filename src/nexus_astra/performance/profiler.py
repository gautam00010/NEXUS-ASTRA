"""Bottleneck Profiler and Migration Protocol for NEXUS-ASTRA.

Profiles the execution pipeline, identifies hot loops, enforces the
no-premature-optimization policy, and validates migration performance.
"""

from __future__ import annotations

import ast
import cProfile
import json
import logging
import os
import pstats
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

PROFILE_FILE = "pipeline_profile.prof"
HOT_SPOTS_DB = "profiled_hot_spots.json"


class BottleneckProfiler:
    """Sampling/Deterministic Profiler and migration decision engine."""

    def __init__(self, src_root: str | None = None) -> None:
        if src_root is None:
            self_path = Path(__file__).resolve()
            self.src_root = self_path.parent.parent
        else:
            self.src_root = Path(src_root)
        self.project_root = self.src_root.parent

    def profile_full_pipeline(self, pipeline_func=None) -> str:
        """Runs the pipeline under cProfile and outputs a stats report."""
        if pipeline_func is None:
            # Create a mock default function that executes key orchestrator parts
            from nexus_astra.main_v2 import NexusOrchestrator
            orchestrator = NexusOrchestrator()
            
            def run_mock_pipeline():
                data = orchestrator.fetch_all_data()
                features = orchestrator.run_feature_engineering(data)
                regime = orchestrator.run_regime_detection(features)
                base_preds = orchestrator.run_base_models(features, regime)
                composite = orchestrator.run_meta_learner(base_preds)
                filtered = orchestrator.apply_dynamic_filters(composite)
                risk_adj = orchestrator.run_risk_management(filtered)
                cal_adj = orchestrator.run_calendar_effects(risk_adj)
                psy_adj = orchestrator.run_psychology_guards(cal_adj)
                final_alerts = orchestrator.generate_final_signals(psy_adj)
                orchestrator.generate_auto_exits(final_alerts)
            
            pipeline_func = run_mock_pipeline

        prof = cProfile.Profile()
        logger.info("Starting cProfile profiling run...")
        prof.enable()
        pipeline_func()
        prof.disable()
        logger.info("Profiling run complete.")

        prof_path = self.project_root / PROFILE_FILE
        prof.dump_stats(str(prof_path))
        logger.info(f"Stats written to {prof_path}")

        # Check if py-spy is available on the path to suggest flamegraph generation
        py_spy_msg = (
            "To generate a sampling flamegraph, run:\n"
            f"  py-spy record -o profile.svg -- python -m nexus_astra.main_v2 --mode morning"
        )
        logger.info(py_spy_msg)
        
        return str(prof_path)

    def identify_hot_functions(
        self, top_n: int = 5, prof_file: str | None = None
    ) -> List[Dict[str, Any]]:
        """Parses the cProfile output and reports the top N bottleneck functions."""
        if prof_file is None:
            prof_path = self.project_root / PROFILE_FILE
        else:
            prof_path = Path(prof_file)

        if not prof_path.exists():
            # Run a quick profile to generate it
            self.profile_full_pipeline()

        stats = pstats.Stats(str(prof_path))
        stats.sort_stats(pstats.SortKey.CUMULATIVE)
        
        hot_list: List[Dict[str, Any]] = []
        # stats.fcn_list is a list of keys: (filename, line, name)
        # stats.stats is a dict mapping keys to tuples:
        # (cc, nc, tt, ct, callers)
        # cc: call count
        # nc: number of calls
        # tt: total time
        # ct: cumulative time
        
        sorted_keys = sorted(
            stats.stats.items(),
            key=lambda item: item[1][3],  # cumulative time
            reverse=True
        )

        # Filter out system and utility imports to find true codebase functions
        count = 0
        for (filename, line, func_name), (cc, nc, tt, ct, callers) in sorted_keys:
            if "nexus_astra" in filename or ("<" not in filename and "importlib" not in filename):
                # We only want real files
                short_fn = Path(filename).name
                hot_list.append({
                    "function": func_name,
                    "file": short_fn,
                    "filepath": filename,
                    "line": line,
                    "call_count": cc,
                    "cumulative_time": ct,
                    "total_time": tt,
                })
                count += 1
                if count >= top_n:
                    break

        # Save to profiled hot spots database
        db_path = self.project_root / HOT_SPOTS_DB
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(hot_list, f, indent=2)
            
        logger.info(f"Identified top {len(hot_list)} hot functions.")
        return hot_list

    def migration_decision_tree(
        self, hot_functions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Determines the appropriate optimization stage for each hot function."""
        decisions = []
        for fn in hot_functions:
            func_name = fn["function"]
            filepath = fn["filepath"]
            
            decision = {
                "function": func_name,
                "file": fn["file"],
                "cumulative_time": fn["cumulative_time"],
                "recommended_action": "Algorithmic optimization",
                "reason": "Default Python refactoring/algorithmic improvement"
            }
            
            # Check content of file if it exists to classify
            try:
                path = Path(filepath)
                if path.exists():
                    code = path.read_text(encoding="utf-8")
                else:
                    code = ""
            except Exception:
                code = ""

            # Rules:
            # 1. WebSocket/Network I/O -> Go
            if any(term in func_name.lower() or term in code.lower() for term in ["websocket", "aiohttp", "socket", "client_session"]):
                decision["recommended_action"] = "Go microservice (Stage 3)"
                decision["reason"] = "I/O bound network concurrency is best handled by Go connection router"
            # 2. Backtesting/Monte Carlo -> Rust
            elif any(term in func_name.lower() for term in ["monte_carlo", "backtest", "walkforward", "optimal_f", "kelly"]):
                decision["recommended_action"] = "Rust extension module (Stage 2)"
                decision["reason"] = "Highly iterative numerical loop or search algorithm best optimized by Rust"
            # 3. Numerical loops -> NumPy vectorize
            elif "for " in code and any(term in code for term in ["np.", "numpy"]):
                decision["recommended_action"] = "NumPy Vectorization (Stage 1)"
                decision["reason"] = "Identified sequential array loop that can be vectorized using NumPy slicing"
            # 4. DataFrame ops -> Polars
            elif any(term in code for term in ["pd.", "pandas", "groupby", "merge", "iterrows"]):
                decision["recommended_action"] = "Polars expressions (Stage 1)"
                decision["reason"] = "DataFrame manipulation should use Polars lazy evaluation APIs"
                
            decisions.append(decision)
            
        return decisions

    def enforce_no_premature_optimization(self) -> None:
        """Verifies that any Rust/Go references correspond to profiled hot spots."""
        db_path = self.project_root / HOT_SPOTS_DB
        if not db_path.exists():
            logger.warning("No hot spots database found. Run identify_hot_functions() first.")
            return

        with open(db_path, "r", encoding="utf-8") as f:
            hot_spots = json.load(f)

        hot_func_names = {item["function"] for item in hot_spots}
        
        # We check files in src/ for rust_engine imports or Go network calls.
        violations = []
        for py_file in self.src_root.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Check if rust_engine is imported or used
            if "rust_engine" in content:
                # Find which functions call it
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if node.name == "enforce_no_premature_optimization":
                            continue
                        # Look inside this function for rust_engine
                        func_code = ast.get_source_segment(content, node)
                        if func_code and "rust_engine" in func_code:
                            if node.name not in hot_func_names:
                                violations.append({
                                    "file": str(py_file.relative_to(self.src_root)),
                                    "function": node.name,
                                    "technology": "Rust",
                                    "reason": f"Function '{node.name}' uses Rust but is NOT in the top-5 profiled bottlenecks."
                                })

            # Check if Go WebSocket router is hit
            if "localhost:8080" in content:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if node.name == "enforce_no_premature_optimization":
                            continue
                        func_code = ast.get_source_segment(content, node)
                        if func_code and "localhost:8080" in func_code:
                            if node.name not in hot_func_names:
                                violations.append({
                                    "file": str(py_file.relative_to(self.src_root)),
                                    "function": node.name,
                                    "technology": "Go",
                                    "reason": f"Function '{node.name}' uses Go WebSocket route but is NOT in the top-5 profiled bottlenecks."
                                })

        if violations:
            err_msg = "\n".join(
                f"- {v['file']}:{v['function']} ({v['technology']}): {v['reason']}"
                for v in violations
            )
            raise AssertionError(
                "PREMATURE OPTIMIZATION VIOLATION:\n"
                "You are attempting to use Rust/Go optimization for unprofiled pathways!\n"
                f"{err_msg}"
            )
        else:
            logger.info("Premature optimization check passed: All Rust/Go modules mapped to profiled bottlenecks.")

    def performance_regression_test(
        self, func_name: str, before_time: float, after_time: float
    ) -> Dict[str, Any]:
        """Compares migration timing. Rejects if speedup < 5x."""
        if after_time <= 0:
            speedup = float('inf')
        else:
            speedup = before_time / after_time

        result = {
            "function": func_name,
            "before_time_ms": before_time,
            "after_time_ms": after_time,
            "speedup_factor": speedup,
            "passed": speedup >= 5.0
        }

        if not result["passed"]:
            logger.warning(
                f"WARNING: Speedup for '{func_name}' was only {speedup:.2f}x. "
                "MIGRATION_NOT_WORTH_COMPLEXITY (Target: >= 5.0x)"
            )
        else:
            logger.info(f"SUCCESS: Speedup for '{func_name}' is {speedup:.2f}x.")

        return result
