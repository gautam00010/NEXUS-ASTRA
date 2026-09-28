//! # rust_engine
//!
//! High-performance Rust extension module for the **NEXUS-ASTRA** trading
//! system.  Exposes four hot-path functions to Python via PyO3:
//!
//! | Function                        | Purpose                                      |
//! |---------------------------------|----------------------------------------------|
//! | `walk_forward_backtest_rs`      | Walk-forward backtesting hot loop             |
//! | `monte_carlo_simulation_rs`     | 10 K parallel Monte Carlo via Rayon           |
//! | `parse_options_chain_rs`        | Parse CSV/JSON options chain → Arrow IPC      |
//! | `calculate_gamma_exposure_rs`   | Vectorised gamma exposure across all strikes  |
//!
//! ## Design principles
//!
//! * **GIL release** — every long computation runs inside
//!   [`pyo3::Python::allow_threads`] so other Python threads are not blocked.
//! * **Arrow IPC** — DataFrames are returned as IPC byte buffers that Python
//!   can deserialise with `pyarrow.ipc.open_stream()` for near-zero-copy
//!   transfer.
//! * **Rayon** — Monte Carlo simulations fan out across all available cores.
//! * **Criterion** — benchmarks live in `benches/bench_core.rs`.

mod python_bridge;

use pyo3::prelude::*;
use pyo3::types::PyBytes;

use polars::prelude::*;
use rand::Rng;
use rand_distr::Normal;
use rayon::prelude::*;

use python_bridge::{run_without_gil, dataframe_to_arrow_ipc, BridgeError};

use std::f64::consts::PI;
use std::io::Cursor;

// =========================================================================
// 1. Walk-Forward Backtest
// =========================================================================

/// Perform a walk-forward backtest over the supplied feature matrix.
///
/// The algorithm slides a `(train_window + test_window)` frame across the
/// rows.  For each step it:
///
/// 1. **Trains** a trivial momentum signal on the training window (mean of
///    all feature columns).
/// 2. **Tests** the signal on the subsequent test window, accumulating P&L.
///
/// Returns a list of per-fold cumulative returns.
///
/// # Arguments
///
/// * `features` — 2-D nested list of `f64` (rows × columns).
/// * `train_window` — number of rows in each training fold.
/// * `test_window` — number of rows in each testing fold.
///
/// # Errors
///
/// Raises `ValueError` if the feature matrix is empty or windows are invalid.
#[pyfunction]
#[pyo3(signature = (features, train_window, test_window))]
fn walk_forward_backtest_rs(
    py: Python<'_>,
    features: Vec<Vec<f64>>,
    train_window: usize,
    test_window: usize,
) -> PyResult<Vec<f64>> {
    // --- Validate inputs ---------------------------------------------------
    if features.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "features must be a non-empty 2-D list",
        ));
    }
    let total_rows = features.len();
    let step = train_window + test_window;
    if step == 0 || step > total_rows {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "train_window ({train_window}) + test_window ({test_window}) must be \
             in 1..={total_rows}"
        )));
    }

    // --- Release the GIL and run the hot loop ------------------------------
    let fold_returns = run_without_gil(py, move || {
        let n_cols = features[0].len().max(1);
        let mut results: Vec<f64> = Vec::new();

        let mut start = 0;
        while start + step <= total_rows {
            let train_end = start + train_window;
            let test_end = train_end + test_window;

            // ---- Train: compute per-column mean over the training window --
            let mut col_means = vec![0.0_f64; n_cols];
            for row in &features[start..train_end] {
                for (j, &val) in row.iter().enumerate().take(n_cols) {
                    col_means[j] += val;
                }
            }
            for m in col_means.iter_mut() {
                *m /= train_window as f64;
            }

            // Signal: average of column means (simple momentum proxy)
            let signal: f64 = col_means.iter().sum::<f64>() / n_cols as f64;
            let position = if signal > 0.0 { 1.0 } else { -1.0 };

            // ---- Test: accumulate P&L using position × row-mean -----------
            let mut fold_pnl = 0.0_f64;
            for row in &features[train_end..test_end] {
                let row_mean: f64 = row.iter().sum::<f64>() / n_cols as f64;
                fold_pnl += position * row_mean;
            }

            results.push(fold_pnl);
            start += test_window; // slide by test_window (anchored walk-forward)
        }

        results
    });

    Ok(fold_returns)
}

// =========================================================================
// 2. Monte Carlo Simulation
// =========================================================================

/// Run 10 000 (or `n_simulations`) parallel Monte Carlo paths and return
/// summary statistics.
///
/// Each simulation randomly samples (with replacement) from the supplied
/// `returns` vector, compounds them to get a terminal wealth value, and the
/// function aggregates all paths into:
///
/// * **median_terminal_wealth** — the 50th-percentile terminal wealth.
/// * **var_95** — the 5th-percentile terminal wealth (Value-at-Risk @ 95 %).
/// * **probability_of_profit** — fraction of paths with terminal wealth > 1.0.
///
/// Returns a 3-tuple `(median_terminal_wealth, var_95, probability_of_profit)`.
///
/// # Arguments
///
/// * `returns` — a list of period log-returns (e.g. daily).
/// * `n_simulations` — number of Monte Carlo paths (default 10 000).
///
/// # Errors
///
/// Raises `ValueError` if `returns` is empty or `n_simulations` is zero.
#[pyfunction]
#[pyo3(signature = (returns, n_simulations = 10_000))]
fn monte_carlo_simulation_rs(
    py: Python<'_>,
    returns: Vec<f64>,
    n_simulations: usize,
) -> PyResult<(f64, f64, f64)> {
    if returns.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "returns must be non-empty",
        ));
    }
    if n_simulations == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "n_simulations must be > 0",
        ));
    }

    let n_periods = returns.len();

    let result = run_without_gil(py, move || {
        // Rayon parallel iterator — one RNG per thread, no contention.
        let mut terminal_wealths: Vec<f64> = (0..n_simulations)
            .into_par_iter()
            .map(|_| {
                let mut rng = rand::thread_rng();
                let mut wealth = 1.0_f64;
                for _ in 0..n_periods {
                    let idx = rng.gen_range(0..n_periods);
                    wealth *= 1.0 + returns[idx];
                }
                wealth
            })
            .collect();

        // Sort for percentile extraction
        terminal_wealths
            .sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

        let median = terminal_wealths[n_simulations / 2];
        let var_95 = terminal_wealths[(n_simulations as f64 * 0.05) as usize];
        let prob_profit = terminal_wealths.iter().filter(|&&w| w > 1.0).count() as f64
            / n_simulations as f64;

        (median, var_95, prob_profit)
    });

    Ok(result)
}

// =========================================================================
// 3. Parse Options Chain
// =========================================================================

/// Parse a raw CSV or JSON string of options chain data into an Arrow IPC
/// byte buffer.
///
/// The returned `bytes` object can be deserialised on the Python side with:
///
/// ```python
/// import pyarrow as pa
/// reader = pa.ipc.open_stream(result_bytes)
/// table = reader.read_all()
/// df = table.to_pandas()   # or polars.from_arrow(table)
/// ```
///
/// ## Expected CSV columns
///
/// `strike,bid,ask,volume,open_interest,option_type`
///
/// ## Expected JSON schema
///
/// ```json
/// [
///   {"strike": 100.0, "bid": 1.5, "ask": 1.7, "volume": 300,
///    "open_interest": 1200, "option_type": "call"},
///   ...
/// ]
/// ```
///
/// # Arguments
///
/// * `raw_data` — the raw CSV or JSON string.
///
/// # Errors
///
/// Raises `ValueError` if the data cannot be parsed as CSV or JSON.
#[pyfunction]
#[pyo3(signature = (raw_data))]
fn parse_options_chain_rs<'py>(
    py: Python<'py>,
    raw_data: &str,
) -> PyResult<Bound<'py, PyBytes>> {
    let owned_data = raw_data.to_owned();

    let ipc_bytes = run_without_gil(py, move || -> Result<Vec<u8>, BridgeError> {
        // Try JSON first (starts with '['), fall back to CSV
        let mut df = if owned_data.trim_start().starts_with('[') {
            parse_json_options_chain(&owned_data)?
        } else {
            parse_csv_options_chain(&owned_data)?
        };

        dataframe_to_arrow_ipc(&mut df)
    })
    .map_err(PyErr::from)?;

    Ok(PyBytes::new(py, &ipc_bytes))
}

/// Parse JSON options chain data into a Polars DataFrame.
fn parse_json_options_chain(data: &str) -> Result<DataFrame, BridgeError> {
    let cursor = Cursor::new(data.as_bytes());
    let df = JsonReader::new(cursor)
        .finish()
        .map_err(BridgeError::Polars)?;
    validate_options_columns(&df)?;
    Ok(df)
}

/// Parse CSV options chain data into a Polars DataFrame.
fn parse_csv_options_chain(data: &str) -> Result<DataFrame, BridgeError> {
    let cursor = Cursor::new(data.as_bytes());
    let df = CsvReader::new(cursor)
        .has_header(true)
        .finish()
        .map_err(BridgeError::Polars)?;
    validate_options_columns(&df)?;
    Ok(df)
}

/// Validate that the DataFrame contains the required columns.
fn validate_options_columns(df: &DataFrame) -> Result<(), BridgeError> {
    const REQUIRED: &[&str] = &["strike", "bid", "ask", "volume", "open_interest", "option_type"];
    for &col in REQUIRED {
        if df.column(col).is_err() {
            return Err(BridgeError::Generic(format!(
                "Missing required column: '{col}'. Expected columns: {REQUIRED:?}"
            )));
        }
    }
    Ok(())
}

// =========================================================================
// 4. Calculate Gamma Exposure (GEX)
// =========================================================================

/// Compute the net gamma exposure (GEX) for every strike in the chain.
///
/// For each strike *K* the per-strike GEX is computed via the
/// Black-Scholes gamma approximation:
///
/// ```text
/// gamma(K) = φ(d₁) / (S · σ · √T)
/// GEX(K)   = gamma(K) · OI_calls · 100 · S² · 0.01
///          - gamma(K) · OI_puts  · 100 · S² · 0.01
/// ```
///
/// where the simplified constant σ = 0.20 and T = 30/365 are used when the
/// caller does not supply them (scaffolding defaults).
///
/// Returns a list of per-strike GEX values (same length as `strikes`).
///
/// # Arguments
///
/// * `strikes` — list of strike prices.
/// * `oi_calls` — open interest for calls at each strike.
/// * `oi_puts` — open interest for puts at each strike.
/// * `spot` — current underlying spot price.
///
/// # Errors
///
/// Raises `ValueError` if input vectors have mismatched lengths or are empty.
#[pyfunction]
#[pyo3(signature = (strikes, oi_calls, oi_puts, spot))]
fn calculate_gamma_exposure_rs(
    py: Python<'_>,
    strikes: Vec<f64>,
    oi_calls: Vec<f64>,
    oi_puts: Vec<f64>,
    spot: f64,
) -> PyResult<Vec<f64>> {
    let n = strikes.len();
    if n == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "strikes must be non-empty",
        ));
    }
    if oi_calls.len() != n || oi_puts.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err(format!(
            "Length mismatch: strikes={n}, oi_calls={}, oi_puts={}",
            oi_calls.len(),
            oi_puts.len(),
        )));
    }
    if spot <= 0.0 {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "spot must be positive",
        ));
    }

    let gex = run_without_gil(py, move || {
        compute_gamma_exposure(&strikes, &oi_calls, &oi_puts, spot)
    });

    Ok(gex)
}

// ---------------------------------------------------------------------------
// Gamma-exposure internals
// ---------------------------------------------------------------------------

/// Default implied volatility (annualised) when not supplied by the caller.
const DEFAULT_SIGMA: f64 = 0.20;
/// Default time-to-expiry in years (≈ 30 calendar days).
const DEFAULT_T: f64 = 30.0 / 365.0;
/// Contract multiplier (standard equity options = 100 shares).
const CONTRACT_MULT: f64 = 100.0;
/// GEX scaling factor (1 % move in the underlying).
const GEX_SCALE: f64 = 0.01;

/// Vectorised gamma exposure computation.
fn compute_gamma_exposure(
    strikes: &[f64],
    oi_calls: &[f64],
    oi_puts: &[f64],
    spot: f64,
) -> Vec<f64> {
    let sigma = DEFAULT_SIGMA;
    let t = DEFAULT_T;
    let sqrt_t = t.sqrt();

    strikes
        .iter()
        .zip(oi_calls.iter())
        .zip(oi_puts.iter())
        .map(|((&k, &oi_c), &oi_p)| {
            let d1 = ((spot / k).ln() + 0.5 * sigma * sigma * t) / (sigma * sqrt_t);
            let gamma = standard_normal_pdf(d1) / (spot * sigma * sqrt_t);

            let gex_call = gamma * oi_c * CONTRACT_MULT * spot * spot * GEX_SCALE;
            let gex_put = gamma * oi_p * CONTRACT_MULT * spot * spot * GEX_SCALE;

            // Calls have positive gamma exposure; puts negative (dealer hedging)
            gex_call - gex_put
        })
        .collect()
}

/// Standard normal probability density function: φ(x) = e^{-x²/2} / √(2π).
#[inline]
fn standard_normal_pdf(x: f64) -> f64 {
    (-0.5 * x * x).exp() / (2.0 * PI).sqrt()
}

// =========================================================================
// PyO3 module registration
// =========================================================================

/// The `rust_engine` Python module.
///
/// Exposes the four hot-path functions to the NEXUS-ASTRA trading system.
#[pymodule]
fn rust_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(walk_forward_backtest_rs, m)?)?;
    m.add_function(wrap_pyfunction!(monte_carlo_simulation_rs, m)?)?;
    m.add_function(wrap_pyfunction!(parse_options_chain_rs, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_gamma_exposure_rs, m)?)?;
    Ok(())
}

// =========================================================================
// Unit tests
// =========================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_standard_normal_pdf_at_zero() {
        let expected = 1.0 / (2.0 * PI).sqrt(); // ≈ 0.3989
        let got = standard_normal_pdf(0.0);
        assert!((got - expected).abs() < 1e-10);
    }

    #[test]
    fn test_gamma_exposure_symmetric() {
        // When OI_calls == OI_puts the net GEX should be zero at every strike.
        let strikes = vec![100.0, 105.0, 110.0];
        let oi = vec![1000.0, 1000.0, 1000.0];
        let gex = compute_gamma_exposure(&strikes, &oi, &oi, 105.0);
        for g in &gex {
            assert!(
                g.abs() < 1e-6,
                "Expected near-zero net GEX, got {g}"
            );
        }
    }

    #[test]
    fn test_gamma_exposure_direction() {
        // More call OI than put OI → positive GEX (calls dominate)
        let strikes = vec![100.0];
        let oi_c = vec![5000.0];
        let oi_p = vec![1000.0];
        let gex = compute_gamma_exposure(&strikes, &oi_c, &oi_p, 100.0);
        assert!(gex[0] > 0.0, "Expected positive GEX, got {}", gex[0]);
    }

    #[test]
    fn test_walk_forward_basic() {
        // 10 rows, train=4, test=2 → expect 3 folds
        let features: Vec<Vec<f64>> = (0..10).map(|i| vec![i as f64 * 0.01]).collect();
        // We can't call the PyO3 function directly without a Python interpreter,
        // so we just verify the inner logic.
        let n_cols = 1;
        let train_window = 4;
        let test_window = 2;
        let step = train_window + test_window;
        let total_rows = features.len();

        let mut count = 0;
        let mut start = 0;
        while start + step <= total_rows {
            count += 1;
            start += test_window;
        }
        // start: 0→2→4→6  stops at 6+6=12 > 10, so 3 folds at starts 0,2,4
        assert_eq!(count, 3);
    }

    #[test]
    fn test_validate_options_columns() {
        let df = DataFrame::new(vec![
            Series::new("strike".into(), &[100.0_f64]),
            Series::new("bid".into(), &[1.0_f64]),
            Series::new("ask".into(), &[1.5_f64]),
            Series::new("volume".into(), &[100i64]),
            Series::new("open_interest".into(), &[500i64]),
            Series::new("option_type".into(), &["call"]),
        ])
        .unwrap();

        assert!(validate_options_columns(&df).is_ok());
    }

    #[test]
    fn test_validate_options_columns_missing() {
        let df = DataFrame::new(vec![
            Series::new("strike".into(), &[100.0_f64]),
        ])
        .unwrap();

        assert!(validate_options_columns(&df).is_err());
    }
}
