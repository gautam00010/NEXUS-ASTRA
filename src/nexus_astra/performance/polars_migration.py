"""Polars Migration Auditor and Enforcer for NEXUS-ASTRA.

Scans the codebase for Pandas usage, benchmarks Polars replacements,
audits for unvectorized Python loops, and enforces a no-Pandas policy
via a pre-commit hook.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import textwrap
import time
import tracemalloc
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import polars as pl

logger = logging.getLogger(__name__)

# Files that legitimately bridge Pandas output from third-party libraries
PANDAS_EXEMPTIONS = {
    "data_fetcher.py",      # yfinance returns Pandas → pl.from_pandas()
    "trends_fetcher.py",    # pytrends returns Pandas → pl.from_pandas()
    "social_fetcher.py",    # yfinance returns Pandas via .download()
}

# Polars equivalents for common Pandas patterns
POLARS_EQUIVALENTS: Dict[str, str] = {
    "pd.read_csv(path)":        "pl.read_csv(path)",
    "pd.read_parquet(path)":    "pl.read_parquet(path)",
    "pd.DataFrame(data)":      "pl.DataFrame(data)",
    "df.merge(other, on=col)":  "df.join(other, on=col, how='inner')",
    "df.groupby(col).agg(f)":  "df.group_by(col).agg(f)",
    "df.rolling(n).mean()":    "df.with_columns(pl.col(c).rolling_mean(n))",
    "df.apply(func, axis=1)":  "df.with_columns(pl.struct([cols]).map_elements(func))",
    "df.iterrows()":           "df.iter_rows(named=True)",
    "df.itertuples()":         "df.iter_rows(named=True)",
    "import pandas as pd":     "import polars as pl",
}


class PandasToPolarsMigrator:
    """Audits the codebase for Pandas usage and provides Polars replacements."""

    def __init__(self, src_root: str | None = None) -> None:
        if src_root is None:
            self_path = Path(__file__).resolve()
            # Navigate up from performance/ to nexus_astra/
            self.src_root = self_path.parent.parent
        else:
            self.src_root = Path(src_root)

    # ------------------------------------------------------------------
    # 1. migrate_dataframe_operations
    # ------------------------------------------------------------------

    def migrate_dataframe_operations(self) -> Dict[str, List[Dict[str, Any]]]:
        """Scan src/ for Pandas usage and report findings with Polars replacements."""
        pandas_patterns = [
            r"import pandas",
            r"from pandas",
            r"pd\.read_csv",
            r"pd\.read_parquet",
            r"pd\.DataFrame",
            r"pd\.merge",
            r"pd\.concat",
            r"\.groupby\(",
            r"\.apply\(",
            r"\.iterrows\(",
            r"\.itertuples\(",
            r"pd\.MultiIndex",
            r"pl\.from_pandas",
        ]

        findings: Dict[str, List[Dict[str, Any]]] = {
            "direct_pandas_imports": [],
            "pandas_api_calls": [],
            "bridge_points": [],
        }

        for py_file in self.src_root.rglob("*.py"):
            rel = py_file.relative_to(self.src_root)
            is_exempt = py_file.name in PANDAS_EXEMPTIONS

            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            for line_no, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue

                for pattern in pandas_patterns:
                    if re.search(pattern, stripped):
                        entry = {
                            "file": str(rel),
                            "line": line_no,
                            "code": stripped,
                            "pattern": pattern,
                            "exempt": is_exempt,
                        }

                        # Find best Polars equivalent
                        for pd_pat, pl_equiv in POLARS_EQUIVALENTS.items():
                            if any(kw in stripped for kw in pd_pat.split(".")):
                                entry["polars_equivalent"] = pl_equiv
                                break

                        if "import pandas" in stripped or "from pandas" in stripped:
                            findings["direct_pandas_imports"].append(entry)
                        elif "pl.from_pandas" in stripped:
                            findings["bridge_points"].append(entry)
                        else:
                            findings["pandas_api_calls"].append(entry)
                        break  # one finding per line

        # Summary
        total = sum(len(v) for v in findings.values())
        non_exempt = sum(
            1 for cat in findings.values()
            for f in cat
            if not f.get("exempt", False)
        )
        logger.info(
            f"Pandas audit complete: {total} findings total, "
            f"{non_exempt} non-exempt, "
            f"{len(findings['bridge_points'])} necessary bridge points."
        )

        return findings

    # ------------------------------------------------------------------
    # 2. benchmark_migration
    # ------------------------------------------------------------------

    def benchmark_migration(self) -> Dict[str, Dict[str, float]]:
        """Benchmark Polars vs. baseline on representative dataset sizes."""

        results = {}

        # --- Small dataset: ~1,250 rows (5 years daily) ---
        np.random.seed(42)
        n_small = 1250
        dates_small = pl.date_range(
            pl.date(2020, 1, 1), pl.date(2024, 12, 13), eager=True
        )[:n_small]
        small_df = pl.DataFrame({
            "date": dates_small,
            "open": np.linspace(15000, 25000, n_small),
            "high": np.linspace(15100, 25100, n_small),
            "low": np.linspace(14900, 24900, n_small),
            "close": np.linspace(15050, 25050, n_small),
            "volume": np.linspace(100_000, 10_000_000, n_small).astype(int),
        })

        # --- Large dataset: ~100K rows (1-min options chain) ---
        n_large = 100_000
        large_df = pl.DataFrame({
            "timestamp": range(n_large),
            "strike": np.linspace(15000, 25000, n_large),
            "call_oi": np.linspace(1000, 500_000, n_large).astype(int),
            "put_oi": np.linspace(1000, 500_000, n_large).astype(int),
            "call_ltp": np.linspace(10, 500, n_large),
            "put_ltp": np.linspace(10, 500, n_large),
            "spot": np.full(n_large, 22000.0),
        })

        # Benchmark: Rolling mean (20-period)
        results["rolling_mean_small"] = self._bench(
            "Rolling Mean (1.25K rows)",
            lambda: small_df.with_columns(
                pl.col("close").rolling_mean(20).alias("sma_20")
            ),
        )

        results["rolling_mean_large"] = self._bench(
            "Rolling Mean (100K rows)",
            lambda: large_df.with_columns(
                pl.col("strike").rolling_mean(20).alias("sma_20")
            ),
        )

        # Benchmark: GroupBy aggregation
        large_with_group = large_df.with_columns(
            (pl.col("timestamp") % 100).alias("group_key")
        )
        results["groupby_agg_large"] = self._bench(
            "GroupBy Agg (100K rows)",
            lambda: large_with_group.group_by("group_key").agg([
                pl.col("call_oi").sum(),
                pl.col("put_oi").mean(),
                pl.col("strike").max(),
            ]),
        )

        # Benchmark: Filter + Sort
        results["filter_sort_large"] = self._bench(
            "Filter+Sort (100K rows)",
            lambda: large_df.filter(
                pl.col("call_oi") > 250_000
            ).sort("strike"),
        )

        # Benchmark: Join
        lookup = pl.DataFrame({
            "strike": np.arange(15000, 25001, 50, dtype=float),
            "sector": ["A"] * len(np.arange(15000, 25001, 50)),
        })
        results["join_large"] = self._bench(
            "Join (100K rows)",
            lambda: large_df.join(
                lookup, on="strike", how="left"
            ),
        )

        # Benchmark: Lazy evaluation chain
        results["lazy_chain_large"] = self._bench(
            "Lazy Chain (100K rows)",
            lambda: (
                large_df.lazy()
                .filter(pl.col("call_oi") > 100_000)
                .with_columns(
                    (pl.col("call_oi") / pl.col("put_oi")).alias("pcr"),
                    (pl.col("strike") - pl.col("spot")).alias("distance"),
                )
                .group_by(
                    (pl.col("strike") / 500).cast(pl.Int32).alias("bucket")
                )
                .agg(pl.col("pcr").mean())
                .sort("bucket")
                .collect()
            ),
        )

        return results

    def _bench(
        self, label: str, func, iterations: int = 100
    ) -> Dict[str, float]:
        """Run a function multiple times and report timing + memory."""
        # Warm up
        func()

        tracemalloc.start()
        start = time.perf_counter()
        for _ in range(iterations):
            func()
        elapsed = time.perf_counter() - start
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        avg_ms = (elapsed / iterations) * 1000
        logger.info(f"  {label}: {avg_ms:.3f} ms/op, peak mem: {peak_mem / 1024:.1f} KB")

        return {
            "label": label,
            "avg_ms": avg_ms,
            "total_s": elapsed,
            "peak_memory_kb": peak_mem / 1024,
            "iterations": iterations,
        }

    # ------------------------------------------------------------------
    # 3. numpy_vectorization_audit
    # ------------------------------------------------------------------

    def numpy_vectorization_audit(self) -> List[Dict[str, Any]]:
        """Scan for Python for-loops doing math on array-like data."""

        warnings: List[Dict[str, Any]] = []

        # Patterns that suggest array-based math inside a loop body
        math_indicators = re.compile(
            r"arr\[|np\.|\.sum\(|\.mean\(|\*=|\+=|-=|/=|"
            r"returns\[|prices\[|series\[|values\[|equity\["
        )

        for py_file in self.src_root.rglob("*.py"):
            rel = str(py_file.relative_to(self.src_root))

            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except Exception:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.For):
                    # Check if the loop iterates over range()
                    is_range_loop = (
                        isinstance(node.iter, ast.Call)
                        and isinstance(node.iter.func, ast.Name)
                        and node.iter.func.id == "range"
                    )
                    if not is_range_loop:
                        continue

                    # Get the source lines of the loop body
                    body_lines = []
                    for child in ast.walk(node):
                        if hasattr(child, "lineno"):
                            line_no = child.lineno
                            src_lines = source.splitlines()
                            if 0 < line_no <= len(src_lines):
                                body_lines.append(src_lines[line_no - 1])

                    body_text = "\n".join(body_lines)

                    if math_indicators.search(body_text):
                        # Determine if it's in a retry/setup context
                        # (skip retry loops, only flag math loops)
                        first_line = source.splitlines()[node.lineno - 1].strip()
                        if "attempt" in first_line or "retries" in first_line:
                            continue

                        warnings.append({
                            "file": rel,
                            "line": node.lineno,
                            "loop_header": first_line,
                            "severity": "PERFORMANCE_WARNING",
                            "suggestion": "Consider NumPy vectorization or Polars expressions",
                        })

        logger.info(f"Vectorization audit: {len(warnings)} PERFORMANCE_WARNINGs found.")
        return warnings

    # ------------------------------------------------------------------
    # 4. enforce_polars_policy (pre-commit hook)
    # ------------------------------------------------------------------

    def enforce_polars_policy(self) -> str:
        """Generate a pre-commit hook script that blocks new Pandas imports."""

        hook_script = textwrap.dedent("""\
            #!/bin/sh
            # NEXUS-ASTRA Pre-Commit Hook: Enforce Polars-only policy
            # Generated by PandasToPolarsMigrator
            #
            # This hook blocks commits that introduce new Pandas imports.
            # Exemptions are listed below for files that bridge third-party
            # library output (yfinance, pytrends) into Polars.

            EXEMPT_FILES="data_fetcher.py|trends_fetcher.py|social_fetcher.py"

            STAGED_PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\\.py$')

            if [ -z "$STAGED_PY_FILES" ]; then
                exit 0
            fi

            VIOLATIONS=""

            for file in $STAGED_PY_FILES; do
                # Skip exempt files
                basename=$(basename "$file")
                if echo "$basename" | grep -qE "^($EXEMPT_FILES)$"; then
                    continue
                fi

                # Check for pandas imports in staged content
                MATCHES=$(git diff --cached -- "$file" | grep '^+' | grep -v '^+++' | grep -E 'import pandas|from pandas')
                if [ -n "$MATCHES" ]; then
                    VIOLATIONS="$VIOLATIONS\\n  $file:\\n$MATCHES"
                fi
            done

            if [ -n "$VIOLATIONS" ]; then
                echo ""
                echo "============================================================"
                echo "  BLOCKED: New Pandas import detected!"
                echo "============================================================"
                echo ""
                echo "NEXUS-ASTRA enforces a Polars-only policy."
                echo "The following files introduce Pandas imports:"
                echo ""
                printf "$VIOLATIONS\\n"
                echo ""
                echo "Polars equivalents:"
                echo "  import pandas as pd       →  import polars as pl"
                echo "  pd.read_csv(path)         →  pl.read_csv(path)"
                echo "  pd.DataFrame(data)        →  pl.DataFrame(data)"
                echo "  df.merge(other, on=col)   →  df.join(other, on=col)"
                echo "  df.groupby(col).agg(f)    →  df.group_by(col).agg(f)"
                echo "  df.apply(func, axis=1)    →  Use pl.struct().map_elements()"
                echo "  df.iterrows()             →  df.iter_rows(named=True)"
                echo ""
                echo "If this is a legitimate bridge (e.g., yfinance output),"
                echo "add the file to EXEMPT_FILES in .git/hooks/pre-commit."
                echo "============================================================"
                exit 1
            fi

            exit 0
        """)

        # Write to .git/hooks/pre-commit if .git exists
        git_hooks_dir = self.src_root.parent.parent / ".git" / "hooks"
        if git_hooks_dir.exists():
            hook_path = git_hooks_dir / "pre-commit"
            hook_path.write_text(hook_script, encoding="utf-8")
            logger.info(f"Pre-commit hook installed at {hook_path}")
        else:
            logger.warning("No .git/hooks directory found. Hook script generated but not installed.")

        return hook_script
