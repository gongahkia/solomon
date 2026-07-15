// SPDX-License-Identifier: MIT

//! Versioned repository-to-shard placement contracts.

use crate::model::ScopeId;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use thiserror::Error;

/// Current shard-placement schema version.
pub const SHARD_PLACEMENT_SCHEMA_VERSION: u16 = 1;

/// Explicit repository migration state.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ShardMigrationState {
    /// The active shard is the sole owner.
    Stable,
    /// Data is being copied to a future shard; the active shard still owns traffic.
    Preparing,
    /// The active shard remains authoritative while replay is verified.
    Verifying,
    /// The active shard has changed after a successful cutover.
    Cutover,
    /// Migration was abandoned; the active shard remains authoritative.
    RolledBack,
}

/// One repository's routing and migration metadata.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ShardPlacement {
    /// Contract schema version.
    pub schema_version: u16,
    /// Repository resolved by this placement.
    pub repository: ScopeId,
    /// Exactly one authoritative shard for request routing.
    pub active_shard: ScopeId,
    /// Optional future shard during migration.
    pub migration_shard: Option<ScopeId>,
    /// Current migration lifecycle state.
    pub migration_state: ShardMigrationState,
}

impl ShardPlacement {
    /// Creates a stable, single-owner placement.
    #[must_use]
    pub fn stable(repository: ScopeId, active_shard: ScopeId) -> Self {
        Self {
            schema_version: SHARD_PLACEMENT_SCHEMA_VERSION,
            repository,
            active_shard,
            migration_shard: None,
            migration_state: ShardMigrationState::Stable,
        }
    }

    /// Validates ownership and migration invariants.
    ///
    /// # Errors
    ///
    /// Returns a stable contract error when schema or migration metadata is invalid.
    pub fn validate(&self) -> Result<(), RoutingError> {
        if self.schema_version != SHARD_PLACEMENT_SCHEMA_VERSION {
            return Err(RoutingError::Schema);
        }
        match self.migration_state {
            ShardMigrationState::Stable
            | ShardMigrationState::Cutover
            | ShardMigrationState::RolledBack
                if self.migration_shard.is_some() =>
            {
                Err(RoutingError::InvalidMigration)
            }
            ShardMigrationState::Preparing | ShardMigrationState::Verifying
                if self.migration_shard.is_none() =>
            {
                Err(RoutingError::InvalidMigration)
            }
            _ => Ok(()),
        }
    }
}

/// Fail-closed repository placement resolver.
#[derive(Default)]
pub struct ShardRoutingTable {
    placements: BTreeMap<ScopeId, ShardPlacement>,
}

impl ShardRoutingTable {
    /// Registers one validated placement; duplicate repository ownership is rejected.
    ///
    /// # Errors
    ///
    /// Returns a stable error for invalid or duplicate placement metadata.
    pub fn register(&mut self, placement: ShardPlacement) -> Result<(), RoutingError> {
        placement.validate()?;
        if self
            .placements
            .insert(placement.repository.clone(), placement)
            .is_some()
        {
            return Err(RoutingError::DuplicateRepository);
        }
        Ok(())
    }

    /// Resolves exactly one active shard for a repository.
    ///
    /// # Errors
    ///
    /// Returns [`RoutingError::UnassignedRepository`] when no active owner exists.
    pub fn resolve(&self, repository: &ScopeId) -> Result<&ShardPlacement, RoutingError> {
        self.placements
            .get(repository)
            .ok_or(RoutingError::UnassignedRepository)
    }
}

/// Routing-contract failure.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum RoutingError {
    /// Placement schema is unsupported.
    #[error("unsupported shard placement schema")]
    Schema,
    /// Migration fields conflict with the lifecycle state.
    #[error("invalid shard migration metadata")]
    InvalidMigration,
    /// A repository was registered more than once.
    #[error("repository already has a shard placement")]
    DuplicateRepository,
    /// No shard owns the repository.
    #[error("repository has no active shard")]
    UnassignedRepository,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> ScopeId {
        ScopeId::new(value).expect("constant scope")
    }

    #[test]
    fn repository_resolves_to_one_active_shard_through_migration() {
        let mut table = ShardRoutingTable::default();
        let mut placement = ShardPlacement::stable(id("repo"), id("shard-a"));
        placement.migration_shard = Some(id("shard-b"));
        placement.migration_state = ShardMigrationState::Verifying;
        table
            .register(placement)
            .expect("placement should register");
        assert_eq!(
            table.resolve(&id("repo")).expect("placement").active_shard,
            id("shard-a")
        );
        assert!(matches!(
            table.resolve(&id("missing")),
            Err(RoutingError::UnassignedRepository)
        ));
    }

    #[test]
    fn placement_contract_is_versioned_and_fail_closed() {
        let mut placement = ShardPlacement::stable(id("repo"), id("shard"));
        placement.schema_version = 2;
        assert_eq!(placement.validate(), Err(RoutingError::Schema));
        placement.schema_version = SHARD_PLACEMENT_SCHEMA_VERSION;
        placement.migration_state = ShardMigrationState::Preparing;
        assert_eq!(placement.validate(), Err(RoutingError::InvalidMigration));
    }
}
