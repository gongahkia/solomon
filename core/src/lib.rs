// SPDX-License-Identifier: MIT

#![doc = include_str!("../README.md")]

pub mod encryption;
pub mod model;
pub mod storage;
pub mod vector;

/// Current crate version, kept available to bindings and smoke tests.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Returns the crate version.
#[must_use]
pub fn version() -> &'static str {
    VERSION
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_matches_package_metadata() {
        assert_eq!(version(), env!("CARGO_PKG_VERSION"));
    }
}
