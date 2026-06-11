// SPDX-License-Identifier: MIT

//! `PyO3` module for the Shibahama Python package.

use pyo3::prelude::*;

/// Returns the Shibahama core crate version.
#[pyfunction]
fn version() -> &'static str {
    shibahama_core::version()
}

/// Python extension module entry point.
#[pymodule]
fn _shibahama(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", shibahama_core::version())?;
    module.add_function(wrap_pyfunction!(version, module)?)?;

    Ok(())
}
