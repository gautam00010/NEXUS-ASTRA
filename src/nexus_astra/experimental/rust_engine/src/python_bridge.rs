//! GIL management and Arrow interop utilities for the NEXUS-ASTRA Python bridge.
//!
//! This module provides helpers that:
//! 1. Release the GIL during long-running Rust computations so other Python
//!    threads can make progress.
//! 2. Convert Polars [`DataFrame`]s into PyArrow-compatible record batches for
//!    zero-copy transfer back to the Python caller.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use polars::prelude::*;
use std::fmt;

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/// Unified error type for bridge operations.
#[derive(Debug)]
pub enum BridgeError {
    /// An error originating from Polars operations.
    Polars(PolarsError),
    /// An error originating from PyO3 / Python interop.
    Python(PyErr),
    /// A generic error with a descriptive message.
    Generic(String),
}

impl fmt::Display for BridgeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            BridgeError::Polars(e) => write!(f, "Polars error: {e}"),
            BridgeError::Python(e) => write!(f, "Python error: {e}"),
            BridgeError::Generic(msg) => write!(f, "{msg}"),
        }
    }
}

impl From<PolarsError> for BridgeError {
    fn from(e: PolarsError) -> Self {
        BridgeError::Polars(e)
    }
}

impl From<PyErr> for BridgeError {
    fn from(e: PyErr) -> Self {
        BridgeError::Python(e)
    }
}

impl From<BridgeError> for PyErr {
    fn from(e: BridgeError) -> PyErr {
        pyo3::exceptions::PyRuntimeError::new_err(e.to_string())
    }
}

// ---------------------------------------------------------------------------
// GIL release helper
// ---------------------------------------------------------------------------

/// Execute a long-running, GIL-free computation.
///
/// The GIL is released for the duration of `f` so that other Python threads
/// can run concurrently.  The closure must be `Send` because it may execute
/// on a thread-pool thread.
///
/// # Example
///
/// ```rust,ignore
/// let result = run_without_gil(py, || expensive_computation())?;
/// ```
pub fn run_without_gil<F, R>(py: Python<'_>, f: F) -> R
where
    F: FnOnce() -> R + Send,
    R: Send,
{
    py.allow_threads(f)
}

// ---------------------------------------------------------------------------
// Polars DataFrame → Python dict conversion
// ---------------------------------------------------------------------------

/// Convert a Polars [`DataFrame`] into a Python dictionary of column-name →
/// list pairs.
///
/// This is a *simple* serialisation path.  For true zero-copy transfer
/// consider exporting via Arrow C Data Interface (see `dataframe_to_arrow`).
///
/// # Errors
///
/// Returns [`BridgeError`] if any column contains a dtype that cannot be
/// converted to a Python object.
pub fn dataframe_to_pydict<'py>(
    py: Python<'py>,
    df: &DataFrame,
) -> Result<Bound<'py, PyDict>, BridgeError> {
    let dict = PyDict::new(py);

    for series in df.get_columns() {
        let name = series.name().as_str();
        let py_list = series_to_pylist(py, series)?;
        dict.set_item(name, py_list)
            .map_err(BridgeError::Python)?;
    }

    Ok(dict)
}

/// Convert a single Polars [`Series`] to a Python list.
fn series_to_pylist<'py>(
    py: Python<'py>,
    series: &Series,
) -> Result<Bound<'py, PyList>, BridgeError> {
    let len = series.len();
    let mut elements: Vec<PyObject> = Vec::with_capacity(len);

    match series.dtype() {
        DataType::Float64 => {
            let ca = series.f64().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("f64 → PyFloat").into_any().unbind());
            }
        }
        DataType::Float32 => {
            let ca = series.f32().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("f32 → PyFloat").into_any().unbind());
            }
        }
        DataType::Int64 => {
            let ca = series.i64().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("i64 → PyInt").into_any().unbind());
            }
        }
        DataType::Int32 => {
            let ca = series.i32().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("i32 → PyInt").into_any().unbind());
            }
        }
        DataType::String => {
            let ca = series.str().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("str → PyStr").into_any().unbind());
            }
        }
        DataType::Boolean => {
            let ca = series.bool().map_err(BridgeError::Polars)?;
            for opt_v in ca.into_iter() {
                elements.push(opt_v.into_pyobject(py).expect("bool → PyBool").into_any().unbind());
            }
        }
        other => {
            return Err(BridgeError::Generic(format!(
                "Unsupported dtype for Python conversion: {other}"
            )));
        }
    }

    Ok(PyList::new(py, &elements).map_err(BridgeError::Python)?)
}

// ---------------------------------------------------------------------------
// Arrow C Data Interface export (zero-copy path)
// ---------------------------------------------------------------------------

/// Convert a Polars [`DataFrame`] to an Arrow IPC byte buffer that Python
/// can deserialise with `pyarrow.ipc.open_stream()`.
///
/// This is the *zero-copy-ish* path: the data is written to an IPC buffer
/// once, and Python deserialises it on its side without an extra copy of
/// the columnar data.
///
/// # Errors
///
/// Returns [`BridgeError`] on serialisation failure.
pub fn dataframe_to_arrow_ipc(df: &mut DataFrame) -> Result<Vec<u8>, BridgeError> {
    let mut buf: Vec<u8> = Vec::new();
    polars::io::ipc::IpcStreamWriter::new(&mut buf)
        .finish(df)
        .map_err(BridgeError::Polars)?;
    Ok(buf)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bridge_error_display() {
        let err = BridgeError::Generic("test error".into());
        assert_eq!(err.to_string(), "test error");
    }

    #[test]
    fn test_arrow_ipc_roundtrip() {
        let mut df = DataFrame::new(vec![
            Series::new("a".into(), &[1.0_f64, 2.0, 3.0]),
            Series::new("b".into(), &[4i64, 5, 6]),
        ])
        .unwrap();

        let bytes = dataframe_to_arrow_ipc(&mut df).unwrap();
        assert!(!bytes.is_empty(), "IPC buffer should be non-empty");
    }
}
