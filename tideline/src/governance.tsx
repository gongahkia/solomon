import React from "react";

export type Scope = {
  repository: string;
  team: string | null;
  visibility: string;
};

export type GovernanceEvent = {
  sequence: number;
  kind: string;
  permitted_scope: Scope | null;
  policy_outcome: {
    operation: string;
    disposition: string;
    policy_version: number;
  } | null;
  promotion_lineage: {
    source_id: string | null;
    promoted_id: string | null;
    actor: string;
  } | null;
  erasure_tombstone: {
    schema_version: number;
    memory_id: string;
    scope: Scope;
    erased_at_unix: number;
    destroyed_record_key_count: number;
    integrity_hash: string;
  } | null;
};

function scopeLabel(scope: Scope) {
  return `${scope.repository}${scope.team ? ` / ${scope.team}` : ""} (${scope.visibility})`;
}

function shortId(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

export function GovernanceView({ events }: { events: GovernanceEvent[] }) {
  const entries = events.filter(
    (event) => event.policy_outcome || event.promotion_lineage || event.erasure_tombstone,
  );

  return (
    <section className="panel wide-panel governance-panel">
      <div className="panel-title">
        <h2>Scope Governance</h2>
        <span>{entries.length}</span>
      </div>
      {entries.length === 0 ? <p className="empty">No policy, sharing, or erasure records in this scope</p> : null}
      <div className="governance-list">
        {entries.map((event) => (
          <article key={event.sequence} className="governance-row">
            <span>#{event.sequence}</span>
            {event.policy_outcome ? (
              <div>
                <strong>{event.policy_outcome.operation} {event.policy_outcome.disposition}</strong>
                <p>Policy v{event.policy_outcome.policy_version}</p>
                {event.permitted_scope ? <em>{scopeLabel(event.permitted_scope)}</em> : null}
              </div>
            ) : null}
            {event.promotion_lineage ? (
              <div>
                <strong>Promotion lineage</strong>
                <p>
                  {event.promotion_lineage.source_id ? `source ${shortId(event.promotion_lineage.source_id)}` : ""}
                  {event.promotion_lineage.promoted_id ? ` promoted ${shortId(event.promotion_lineage.promoted_id)}` : ""}
                </p>
                <em>{event.promotion_lineage.actor}</em>
              </div>
            ) : null}
            {event.erasure_tombstone ? (
              <div>
                <strong>Erasure tombstone</strong>
                <p>{shortId(event.erasure_tombstone.memory_id)} · {event.erasure_tombstone.destroyed_record_key_count} record keys destroyed</p>
                <em>{scopeLabel(event.erasure_tombstone.scope)}</em>
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
