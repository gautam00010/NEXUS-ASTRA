//! Criterion benchmarks for the NEXUS-ASTRA rust_engine core functions.
//!
//! Run with:
//! ```sh
//! cargo bench
//! ```
//!
//! HTML reports are generated in `target/criterion/`.

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion};
use rand::Rng;
use rayon::prelude::*;
use std::f64::consts::PI;
use std::io::Cursor;

// ---------------------------------------------------------------------------
// We benchmark the *inner* (pure-Rust) logic directly so that we don't need
// a Python interpreter.  The functions below mirror the implementations in
// src/lib.rs.
// ---------------------------------------------------------------------------

// ---- helpers (duplicated from lib.rs so the bench crate is self-contained) -

#[inline]
fn standard_normal_pdf(x: f64) -> f64 {
    (-0.5 * x * x).exp() / (2.0 * PI).sqrt()
}

fn compute_gamma_exposure(
    strikes: &[f64],
    oi_calls: &[f64],
    oi_puts: &[f64],
    spot: f64,
) -> Vec<f64> {
    let sigma: f64 = 0.20;
    let t: f64 = 30.0 / 365.0;
    let sqrt_t = t.sqrt();

    strikes
        .iter()
        .zip(oi_calls.iter())
        .zip(oi_puts.iter())
        .map(|((&k, &oi_c), &oi_p)| {
            let d1 = ((spot / k).ln() + 0.5 * sigma * sigma * t) / (sigma * sqrt_t);
            let gamma = standard_normal_pdf(d1) / (spot * sigma * sqrt_t);
            let gex_call = gamma * oi_c * 100.0 * spot * spot * 0.01;
            let gex_put = gamma * oi_p * 100.0 * spot * spot * 0.01;
            gex_call - gex_put
        })
        .collect()
}

fn walk_forward_inner(
    features: &[Vec<f64>],
    train_window: usize,
    test_window: usize,
) -> Vec<f64> {
    let total_rows = features.len();
    let step = train_window + test_window;
    let n_cols = features[0].len().max(1);
    let mut results: Vec<f64> = Vec::new();

    let mut start = 0;
    while start + step <= total_rows {
        let train_end = start + train_window;
        let test_end = train_end + test_window;

        let mut col_means = vec![0.0_f64; n_cols];
        for row in &features[start..train_end] {
            for (j, &val) in row.iter().enumerate().take(n_cols) {
                col_means[j] += val;
            }
        }
        for m in col_means.iter_mut() {
            *m /= train_window as f64;
        }

        let signal: f64 = col_means.iter().sum::<f64>() / n_cols as f64;
        let position = if signal > 0.0 { 1.0 } else { -1.0 };

        let mut fold_pnl = 0.0_f64;
        for row in &features[train_end..test_end] {
            let row_mean: f64 = row.iter().sum::<f64>() / n_cols as f64;
            fold_pnl += position * row_mean;
        }

        results.push(fold_pnl);
        start += test_window;
    }

    results
}

fn monte_carlo_inner(returns: &[f64], n_simulations: usize) -> (f64, f64, f64) {
    let n_periods = returns.len();

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

    terminal_wealths.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let median = terminal_wealths[n_simulations / 2];
    let var_95 = terminal_wealths[(n_simulations as f64 * 0.05) as usize];
    let prob_profit = terminal_wealths.iter().filter(|&&w| w > 1.0).count() as f64
        / n_simulations as f64;

    (median, var_95, prob_profit)
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

fn bench_walk_forward(c: &mut Criterion) {
    let mut group = c.benchmark_group("walk_forward_backtest");

    for &n_rows in &[500, 2_000, 10_000] {
        let features: Vec<Vec<f64>> = (0..n_rows)
            .map(|i| {
                let v = (i as f64) * 0.001 - 0.5;
                vec![v, v * 1.1, v * 0.9, v * 1.05]
            })
            .collect();

        group.bench_with_input(
            BenchmarkId::from_parameter(n_rows),
            &features,
            |b, feats| {
                b.iter(|| {
                    walk_forward_inner(black_box(feats), 60, 20)
                });
            },
        );
    }

    group.finish();
}

fn bench_monte_carlo(c: &mut Criterion) {
    let mut group = c.benchmark_group("monte_carlo_simulation");

    // Generate synthetic daily returns ≈ N(0.0005, 0.02)
    let mut rng = rand::thread_rng();
    let returns: Vec<f64> = (0..252)
        .map(|_| 0.0005 + 0.02 * rng.gen_range(-1.0..1.0_f64))
        .collect();

    for &n_sims in &[1_000, 10_000, 50_000] {
        group.bench_with_input(
            BenchmarkId::from_parameter(n_sims),
            &n_sims,
            |b, &n| {
                b.iter(|| {
                    monte_carlo_inner(black_box(&returns), n)
                });
            },
        );
    }

    group.finish();
}

fn bench_parse_options_chain(c: &mut Criterion) {
    // Build a CSV string with 500 rows
    let mut csv_data = String::from("strike,bid,ask,volume,open_interest,option_type\n");
    for i in 0..500 {
        let strike = 80.0 + (i as f64) * 0.5;
        let kind = if i % 2 == 0 { "call" } else { "put" };
        csv_data.push_str(&format!(
            "{strike},{bid},{ask},{vol},{oi},{kind}\n",
            bid = strike * 0.01,
            ask = strike * 0.012,
            vol = 100 + i * 3,
            oi = 500 + i * 7,
        ));
    }

    c.bench_function("parse_options_chain_csv_500", |b| {
        b.iter(|| {
            let cursor = Cursor::new(black_box(csv_data.as_bytes()));
            let _df = polars::prelude::CsvReader::new(cursor)
                .has_header(true)
                .finish()
                .unwrap();
        });
    });
}

fn bench_gamma_exposure(c: &mut Criterion) {
    let mut group = c.benchmark_group("calculate_gamma_exposure");

    for &n_strikes in &[50, 200, 1_000] {
        let strikes: Vec<f64> = (0..n_strikes).map(|i| 80.0 + (i as f64) * 0.5).collect();
        let oi_calls: Vec<f64> = (0..n_strikes).map(|i| 500.0 + (i as f64) * 10.0).collect();
        let oi_puts: Vec<f64> = (0..n_strikes).map(|i| 400.0 + (i as f64) * 8.0).collect();
        let spot = 100.0;

        group.bench_with_input(
            BenchmarkId::from_parameter(n_strikes),
            &n_strikes,
            |b, _| {
                b.iter(|| {
                    compute_gamma_exposure(
                        black_box(&strikes),
                        black_box(&oi_calls),
                        black_box(&oi_puts),
                        black_box(spot),
                    )
                });
            },
        );
    }

    group.finish();
}

criterion_group!(
    benches,
    bench_walk_forward,
    bench_monte_carlo,
    bench_parse_options_chain,
    bench_gamma_exposure
);
criterion_main!(benches);
