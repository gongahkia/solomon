// SPDX-License-Identifier: MIT

//! Open, in-memory desired-state control-plane contracts.

use crate::model::MemoryScope;
use crate::storage::RbacRole;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use thiserror::Error;
use time::OffsetDateTime;

/// Desired lifecycle state for one scoped deployment.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DeploymentLifecycle {
    /// Accepts authorized service traffic.
    Active,
    /// Retained for audit only and no longer accepts new work.
    Retired,
}

/// Operator-configurable desired state, intentionally without credentials.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DeploymentDesiredState {
    /// Exact scope owned by the deployment.
    pub scope: MemoryScope,
    /// Desired lifecycle state.
    pub lifecycle: DeploymentLifecycle,
    /// Desired read/write request budget per minute.
    pub request_budget_per_minute: u32,
}

/// Content-free lifecycle audit record.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DeploymentAuditRecord {
    /// Scope changed.
    pub scope: MemoryScope,
    /// Authenticated actor identifier.
    pub actor: String,
    /// RBAC role required for the operation.
    pub required_role: RbacRole,
    /// Stable operation name.
    pub operation: &'static str,
    /// Change time.
    pub recorded_at: OffsetDateTime,
}

/// Authenticated control-plane actor with an already-resolved scoped RBAC role.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlPlaneActor {
    /// Opaque authenticated principal.
    pub principal: String,
    /// Role authorized for this exact scope.
    pub role: RbacRole,
}

/// Open desired-state controller; runtime credentials remain external.
#[derive(Default)]
pub struct DeploymentControlPlane {
    deployments: HashMap<MemoryScope, DeploymentDesiredState>,
    audit: Vec<DeploymentAuditRecord>,
}

impl DeploymentControlPlane {
    /// Creates one active scoped deployment after caller-side RBAC authorization.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid scope, zero budget, or duplicate scope.
    pub fn create(
        &mut self,
        desired: DeploymentDesiredState,
        actor: ControlPlaneActor,
        at: OffsetDateTime,
    ) -> Result<(), ControlPlaneError> {
        validate_desired(&desired)?;
        require_administrator(&actor)?;
        if self
            .deployments
            .insert(desired.scope.clone(), desired.clone())
            .is_some()
        {
            return Err(ControlPlaneError::AlreadyExists);
        }
        self.append_audit(
            desired.scope,
            actor.principal,
            RbacRole::Administrator,
            "create",
            at,
        );
        Ok(())
    }

    /// Inspects desired state without returning runtime credentials.
    #[must_use]
    pub fn inspect(&self, scope: &MemoryScope) -> Option<&DeploymentDesiredState> {
        self.deployments.get(scope)
    }

    /// Replaces desired state after caller-side RBAC authorization.
    ///
    /// # Errors
    ///
    /// Returns an error for invalid or unknown scope configuration.
    pub fn configure(
        &mut self,
        desired: DeploymentDesiredState,
        actor: ControlPlaneActor,
        at: OffsetDateTime,
    ) -> Result<(), ControlPlaneError> {
        validate_desired(&desired)?;
        require_administrator(&actor)?;
        if !self.deployments.contains_key(&desired.scope) {
            return Err(ControlPlaneError::NotFound);
        }
        self.deployments
            .insert(desired.scope.clone(), desired.clone());
        self.append_audit(
            desired.scope,
            actor.principal,
            RbacRole::Administrator,
            "configure",
            at,
        );
        Ok(())
    }

    /// Retires a deployment while retaining desired state and audit evidence.
    ///
    /// # Errors
    ///
    /// Returns an error when the scope is unknown.
    pub fn retire(
        &mut self,
        scope: &MemoryScope,
        actor: ControlPlaneActor,
        at: OffsetDateTime,
    ) -> Result<(), ControlPlaneError> {
        require_administrator(&actor)?;
        let desired = self
            .deployments
            .get_mut(scope)
            .ok_or(ControlPlaneError::NotFound)?;
        desired.lifecycle = DeploymentLifecycle::Retired;
        self.append_audit(
            scope.clone(),
            actor.principal,
            RbacRole::Administrator,
            "retire",
            at,
        );
        Ok(())
    }

    /// Returns content-free lifecycle audit records for one scope.
    pub fn audit(&self, scope: &MemoryScope) -> impl Iterator<Item = &DeploymentAuditRecord> {
        self.audit
            .iter()
            .filter(move |record| &record.scope == scope)
    }

    fn append_audit(
        &mut self,
        scope: MemoryScope,
        actor: String,
        required_role: RbacRole,
        operation: &'static str,
        recorded_at: OffsetDateTime,
    ) {
        self.audit.push(DeploymentAuditRecord {
            scope,
            actor,
            required_role,
            operation,
            recorded_at,
        });
    }
}

fn validate_desired(desired: &DeploymentDesiredState) -> Result<(), ControlPlaneError> {
    desired
        .scope
        .validate()
        .map_err(|_| ControlPlaneError::InvalidDesiredState)?;
    if desired.request_budget_per_minute == 0 {
        return Err(ControlPlaneError::InvalidDesiredState);
    }
    Ok(())
}

fn require_administrator(actor: &ControlPlaneActor) -> Result<(), ControlPlaneError> {
    if actor.role == RbacRole::Administrator {
        Ok(())
    } else {
        Err(ControlPlaneError::Unauthorized)
    }
}

/// Control-plane contract failure.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum ControlPlaneError {
    #[error("invalid deployment desired state")]
    /// Scope or requested budget is invalid.
    InvalidDesiredState,
    #[error("deployment already exists")]
    /// A deployment already owns the scope.
    AlreadyExists,
    #[error("deployment not found")]
    /// No desired state owns the scope.
    NotFound,
    /// Caller lacks the required administrator role.
    #[error("control-plane administrator role is required")]
    Unauthorized,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn lifecycle_keeps_credentials_external_and_audits_every_mutation() {
        let scope = MemoryScope::default();
        let at = OffsetDateTime::UNIX_EPOCH;
        let mut plane = DeploymentControlPlane::default();
        let desired = DeploymentDesiredState {
            scope: scope.clone(),
            lifecycle: DeploymentLifecycle::Active,
            request_budget_per_minute: 60,
        };
        let actor = ControlPlaneActor {
            principal: "oidc:admin".to_owned(),
            role: RbacRole::Administrator,
        };
        plane
            .create(desired.clone(), actor.clone(), at)
            .expect("create");
        plane
            .configure(
                DeploymentDesiredState {
                    request_budget_per_minute: 120,
                    ..desired
                },
                actor.clone(),
                at,
            )
            .expect("configure");
        plane.retire(&scope, actor, at).expect("retire");
        assert_eq!(
            plane.inspect(&scope).expect("state").lifecycle,
            DeploymentLifecycle::Retired
        );
        assert_eq!(plane.audit(&scope).count(), 3);
        let denied = ControlPlaneActor {
            principal: "oidc:reader".to_owned(),
            role: RbacRole::Reader,
        };
        assert_eq!(
            plane.retire(&scope, denied, at),
            Err(ControlPlaneError::Unauthorized)
        );
    }
}
