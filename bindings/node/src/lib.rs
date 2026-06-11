// SPDX-License-Identifier: MIT

//! `napi-rs` module for the Shibahama Node.js package.

#![allow(missing_docs)]
#![allow(clippy::needless_pass_by_value)]

use napi::bindgen_prelude::*;
use napi_derive::napi;
use shibahama_core::api::{Shibahama as CoreShibahama, ShibahamaError};
use shibahama_core::vector::HnswVectorIndex;
use std::sync::Mutex;

/// In-process Shibahama engine using the built-in HNSW vector index.
#[napi]
pub struct Shibahama {
    inner: Mutex<CoreShibahama<HnswVectorIndex>>,
}

#[napi]
impl Shibahama {
    /// Opens a Shibahama store.
    ///
    /// # Errors
    ///
    /// Returns an error when the durable store cannot be opened.
    #[napi(constructor)]
    pub fn new(path: String, dimensions: u32, capacity: Option<u32>) -> Result<Self> {
        let vector_index =
            HnswVectorIndex::with_capacity(dimensions as usize, capacity.unwrap_or(1024) as usize);
        let inner = CoreShibahama::open(path, vector_index).map_err(js_error)?;

        Ok(Self {
            inner: Mutex::new(inner),
        })
    }

    /// Returns true when the native engine lock is healthy.
    #[napi]
    pub fn is_open(&self) -> bool {
        self.inner.lock().is_ok()
    }
}

/// Returns the Shibahama core crate version.
#[napi]
#[must_use]
pub fn version() -> String {
    shibahama_core::version().to_owned()
}

fn js_error(error: ShibahamaError) -> Error {
    Error::from_reason(error.to_string())
}
