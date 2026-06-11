// SPDX-License-Identifier: MIT

//! Core data model types shared by storage, retrieval, bindings, and the CLI.

use serde::{Deserialize, Serialize};
use std::fmt::{self, Display, Formatter};
use uuid::Uuid;

/// Stable identifier for a persisted memory item.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct MemoryId(Uuid);

impl MemoryId {
    /// Generates a new time-ordered `UUIDv7` memory identifier.
    #[must_use]
    pub fn new_v7() -> Self {
        Self(Uuid::now_v7())
    }

    /// Returns the underlying UUID value.
    #[must_use]
    pub const fn as_uuid(self) -> Uuid {
        self.0
    }
}

impl Display for MemoryId {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Display::fmt(&self.0, f)
    }
}

impl From<Uuid> for MemoryId {
    fn from(value: Uuid) -> Self {
        Self(value)
    }
}

impl From<MemoryId> for Uuid {
    fn from(value: MemoryId) -> Self {
        value.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_memory_ids_are_uuid_v7() {
        let id = MemoryId::new_v7();

        assert_eq!(id.as_uuid().get_version_num(), 7);
    }

    #[test]
    fn generated_memory_ids_are_time_orderable() {
        let first = MemoryId::new_v7();
        let second = MemoryId::new_v7();

        assert!(first < second);
    }
}
