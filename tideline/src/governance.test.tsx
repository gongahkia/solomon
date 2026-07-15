import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { GovernanceView, type GovernanceEvent } from "./governance";

const scope = { repository: "repo-a", team: null, visibility: "private" };

const event: GovernanceEvent = {
  sequence: 7,
  kind: "policy_decision",
  permitted_scope: scope,
  policy_outcome: { operation: "recall", disposition: "allowed", policy_version: 2 },
  promotion_lineage: null,
  erasure_tombstone: null,
};

describe("GovernanceView", () => {
  it("renders only server-projected governance fields", () => {
    const html = renderToStaticMarkup(<GovernanceView events={[event]} />);

    expect(html).toContain("recall allowed");
    expect(html).toContain("repo-a");
    expect(html).not.toContain("requested_candidates");
    expect(html).not.toContain("effective_candidates");
  });

  it("renders a scope-local empty state", () => {
    const html = renderToStaticMarkup(<GovernanceView events={[]} />);

    expect(html).toContain("No policy, sharing, or erasure records in this scope");
    expect(html).not.toContain("other scope");
  });

  it("renders only the scope-projected side of promotion lineage", () => {
    const html = renderToStaticMarkup(
      <GovernanceView
        events={[
          {
            ...event,
            policy_outcome: null,
            promotion_lineage: { source_id: null, promoted_id: "local-promoted-id", actor: "maintainer" },
          },
        ]}
      />,
    );

    expect(html).toContain("Promotion lineage");
    expect(html).toContain("local-pr…d-id");
    expect(html).not.toContain("foreign-source-id");
  });
});
