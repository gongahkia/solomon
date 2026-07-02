import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Download,
  GitCompareArrows,
  Pause,
  Play,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  SquareMousePointer,
  Waypoints,
} from "lucide-react";
import "./styles.css";

type Tier = "hot" | "warm" | "cold" | string;

type MemoryItem = {
  id: string;
  content: string;
  kind: string;
  provenance: {
    source_kind: string;
    source_ref: string | null;
    ingested_by: string;
  };
  tier: Tier;
  credence: string;
  significance: number;
  credence_floor: Tier;
  valid_from_unix: number;
  valid_to_unix: number | null;
  ingested_at_unix: number;
};

type TidelineEvent = {
  sequence: number;
  recorded_at_unix: number;
  kind: string;
  memory_ids: string[];
  tier_from: Tier | null;
  tier_to: Tier | null;
  access_outcome: string | null;
  valid_to_unix: number | null;
  consolidation_action: string | null;
  consolidation_why: string | null;
  consolidation_evidence: ConsolidationEvidence[];
  human_signal_action: string | null;
  human_signal_actor: string | null;
  human_signal_reason: string | null;
};

type ConsolidationEvidence = {
  memory_id: string;
  significance: number;
  access_count: number;
  actual_use_count: number;
  contradiction_count: number;
  tier: Tier;
  credence: string;
  credence_floor: Tier;
};

type TidelineGraphNode = {
  id: string;
  label: string;
  tier: Tier;
  credence: string;
  significance: number;
  valid_from_unix: number;
  valid_to_unix: number | null;
};

type TidelineGraphEdge = {
  id: string;
  from: string;
  to: string;
  kind: string;
  valid_from_unix: number | null;
  valid_to_unix: number | null;
};

type TidelineSnapshot = {
  schema_version: number;
  version: string;
  path: string;
  namespace: string;
  generated_at_unix: number;
  as_of_unix: number | null;
  memory_count: number;
  event_count: number;
  last_sequence: number | null;
  memories: MemoryItem[];
  events: TidelineEvent[];
  graph: {
    nodes: TidelineGraphNode[];
    edges: TidelineGraphEdge[];
  };
};

type EventRecordDetail = {
  sequence: number;
  recorded_at_unix?: number;
  recordedAtUnix?: number;
  kind: string;
  memory_ids?: string[];
  memoryIds?: string[];
  event: unknown;
};

type EventLog = {
  event_count?: number;
  eventCount?: number;
  events: EventRecordDetail[];
};

type WhyTrace = {
  item: MemoryItem;
  significance: {
    base_score: number;
    decay_multiplier: number;
    reinforcement: number;
    outcome_bonus: number;
    contradiction_penalty: number;
    graph_centrality: number;
    final_score: number;
  };
  tier_current: string;
  tier_credence: string;
  tier_credence_floor: string;
  currency_state: string;
  currency_as_of_unix: number;
  valid_from_unix: number;
  valid_to_unix: number | null;
  ingested_at_unix: number;
  audit_trail: string[];
};

type AuditDetail = {
  memory_id?: string;
  memoryId?: string;
  why: WhyTrace | null;
  events: EventRecordDetail[];
};

type ViewName = "moment" | "staleness" | "consolidation" | "poisoning" | "bitemporal" | "graph" | "diff";
type ChallengeNote = { actor: string; reason: string };
type StalenessDecision = {
  event: TidelineEvent;
  superseded: MemoryItem;
  current: MemoryItem | null;
  cutoffUnix: number | null;
};

const API_BASE = "http://127.0.0.1:8765";
const tierOrder: Record<string, number> = { hot: 0, warm: 1, cold: 2 };
const tierLabels = ["hot", "warm", "cold"];

function App() {
  const [baseUrl, setBaseUrl] = useState(API_BASE);
  const [apiKey, setApiKey] = useState("");
  const [namespace, setNamespace] = useState("default");
  const [snapshot, setSnapshot] = useState<TidelineSnapshot | null>(null);
  const [eventLog, setEventLog] = useState<EventLog | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedEventSequence, setSelectedEventSequence] = useState<number | null>(null);
  const [whyTrace, setWhyTrace] = useState<WhyTrace | null>(null);
  const [auditDetail, setAuditDetail] = useState<AuditDetail | null>(null);
  const [status, setStatus] = useState("idle");
  const [live, setLive] = useState(false);
  const [activeView, setActiveView] = useState<ViewName>("moment");
  const [sequence, setSequence] = useState<number>(0);
  const [diffFrom, setDiffFrom] = useState<number>(0);
  const [diffTo, setDiffTo] = useState<number>(0);
  const [exportingClip, setExportingClip] = useState(false);
  const [asOf, setAsOf] = useState("");

  const requestHeaders = useMemo(() => {
    const headers: Record<string, string> = {
      "x-shibahama-namespace": namespace,
    };

    if (apiKey) {
      headers["x-api-key"] = apiKey;
    }

    return headers;
  }, [apiKey, namespace]);

  const loadSnapshot = useCallback(async () => {
    setStatus("loading");
    const asOfParam = asOf ? `?as_of_unix=${Math.floor(new Date(asOf).getTime() / 1000)}` : "";
    const response = await fetch(`${baseUrl}/tideline/snapshot${asOfParam}`, {
      headers: requestHeaders,
    });

    if (!response.ok) {
      throw new Error(`snapshot ${response.status}`);
    }

    const data = (await response.json()) as TidelineSnapshot;
    const eventResponse = await fetch(`${baseUrl}/events${asOfParam}`, {
      headers: requestHeaders,
    });
    const lastSequence = data.last_sequence ?? 0;
    setSnapshot(data);
    if (eventResponse.ok) {
      setEventLog((await eventResponse.json()) as EventLog);
    }
    setSequence(lastSequence);
    setSelectedEventSequence((current) => current ?? lastSequence);
    setDiffFrom((current) => Math.min(current, lastSequence));
    setDiffTo((current) => (current === 0 ? lastSequence : Math.min(current, lastSequence)));
    setSelectedId((current) => current ?? data.memories[0]?.id ?? null);
    setStatus("synced");
  }, [asOf, baseUrl, requestHeaders]);

  const loadWhy = useCallback(
    async (id: string) => {
      const nowParam = asOf ? `?now_unix=${Math.floor(new Date(asOf).getTime() / 1000)}` : "";
      const response = await fetch(`${baseUrl}/why/${id}${nowParam}`, {
        headers: requestHeaders,
      });

      if (!response.ok) {
        throw new Error(`why ${response.status}`);
      }

      setWhyTrace((await response.json()) as WhyTrace | null);
    },
    [asOf, baseUrl, requestHeaders],
  );

  const loadAudit = useCallback(
    async (id: string) => {
      const nowParam = asOf ? `?now_unix=${Math.floor(new Date(asOf).getTime() / 1000)}` : "";
      const response = await fetch(`${baseUrl}/audit/${id}${nowParam}`, {
        headers: requestHeaders,
      });

      if (!response.ok) {
        throw new Error(`audit ${response.status}`);
      }

      setAuditDetail((await response.json()) as AuditDetail);
    },
    [asOf, baseUrl, requestHeaders],
  );

  useEffect(() => {
    loadSnapshot().catch((error) => setStatus(error.message));
  }, [loadSnapshot]);

  useEffect(() => {
    if (!live) {
      return;
    }

    const timer = window.setInterval(() => {
      loadSnapshot().catch((error) => setStatus(error.message));
    }, 1500);

    return () => window.clearInterval(timer);
  }, [live, loadSnapshot]);

  useEffect(() => {
    if (!selectedId) {
      setWhyTrace(null);
      setAuditDetail(null);
      return;
    }

    loadWhy(selectedId).catch(() => setWhyTrace(null));
    loadAudit(selectedId).catch(() => setAuditDetail(null));
  }, [loadAudit, loadWhy, selectedId]);

  const events = snapshot?.events ?? [];
  const maxSequence = snapshot?.last_sequence ?? 0;
  const visibleEvents = events.filter((event) => event.sequence <= sequence);
  const selectedEvent =
    visibleEvents.find((event) => event.sequence === selectedEventSequence) ??
    visibleEvents.at(-1) ??
    null;
  const activeEvent = selectedEvent;
  const rawEvent = useMemo(
    () => (eventLog?.events ?? []).find((event) => event.sequence === selectedEvent?.sequence) ?? null,
    [eventLog, selectedEvent],
  );
  const firstSeen = useMemo(() => {
    const seen = new Map<string, number>();

    for (const event of events) {
      if (event.kind !== "memory_written") {
        continue;
      }

      for (const id of event.memory_ids) {
        seen.set(id, Math.min(seen.get(id) ?? Number.MAX_SAFE_INTEGER, event.sequence));
      }
    }

    return seen;
  }, [events]);
  const visibleMemories = (snapshot?.memories ?? []).filter((memory) => {
    const first = firstSeen.get(memory.id) ?? 0;
    return first <= sequence;
  });
  const stalenessDecisions = useMemo(
    () => buildStalenessDecisions(visibleEvents, visibleMemories),
    [visibleEvents, visibleMemories],
  );
  const selectedMemory = visibleMemories.find((memory) => memory.id === selectedId) ?? null;
  const lowCredence = visibleMemories.filter((memory) =>
    ["unverified", "model_inferred"].includes(memory.credence),
  );
  const momentEvents = visibleEvents.filter((event) =>
    ["memory_invalidated", "reconstruction_applied", "human_signal"].includes(event.kind),
  );
  const consolidationEvents = visibleEvents.filter(
    (event) => event.kind === "consolidation_decision",
  );
  const challengeReasons = useMemo(() => {
    const reasons = new Map<string, ChallengeNote>();

    for (const event of visibleEvents) {
      if (event.kind !== "human_signal" || event.human_signal_action !== "challenge") {
        continue;
      }

      for (const id of event.memory_ids) {
        reasons.set(id, {
          actor: event.human_signal_actor ?? "unknown",
          reason: event.human_signal_reason ?? "challenged",
        });
      }
    }

    return reasons;
  }, [visibleEvents]);
  const contestedIds = useMemo(() => new Set(challengeReasons.keys()), [challengeReasons]);
  const selectedChallenge = selectedId ? challengeReasons.get(selectedId) ?? null : null;

  useEffect(() => {
    if (activeView !== "staleness" || stalenessDecisions.length === 0) {
      return;
    }

    const ids = new Set(
      stalenessDecisions.flatMap((decision) => [
        decision.superseded.id,
        ...(decision.current ? [decision.current.id] : []),
      ]),
    );

    if (!selectedId || !ids.has(selectedId)) {
      setSelectedId(stalenessDecisions[0].current?.id ?? stalenessDecisions[0].superseded.id);
    }
  }, [activeView, selectedId, stalenessDecisions]);

  async function downloadRecording() {
    const asOfParam = asOf ? `?as_of_unix=${Math.floor(new Date(asOf).getTime() / 1000)}` : "";
    const response = await fetch(`${baseUrl}/tideline/recording${asOfParam}`, {
      headers: requestHeaders,
    });
    const recording = await response.json();
    const blob = new Blob([JSON.stringify(recording, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `tideline-${namespace}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function downloadShareableClip() {
    if (!snapshot || exportingClip) {
      return;
    }

    setExportingClip(true);
    setStatus("exporting clip");

    try {
      const blob = await renderShareableClip(snapshot);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");

      anchor.href = url;
      anchor.download = `tideline-${snapshot.namespace}.webm`;
      anchor.click();
      URL.revokeObjectURL(url);
      setStatus("clip exported");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "clip export failed");
    } finally {
      setExportingClip(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Shibahama</p>
          <h1>Tideline</h1>
        </div>
        <div className="status-strip">
          <span>{snapshot?.namespace ?? namespace}</span>
          <span>{snapshot ? `${snapshot.memory_count} memories` : "no snapshot"}</span>
          <span>{status}</span>
        </div>
      </header>

      <section className="control-band">
        <label>
          API
          <input value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
        </label>
        <label>
          Namespace
          <input value={namespace} onChange={(event) => setNamespace(event.target.value)} />
        </label>
        <label>
          Key
          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label>
          As of
          <input type="datetime-local" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </label>
        <button type="button" className="icon-button" title="Refresh" onClick={() => loadSnapshot()}>
          <RefreshCcw size={18} />
        </button>
        <button
          type="button"
          className={live ? "icon-button active" : "icon-button"}
          title={live ? "Pause live" : "Play live"}
          onClick={() => setLive((value) => !value)}
        >
          {live ? <Pause size={18} /> : <Play size={18} />}
        </button>
        <button type="button" className="icon-button" title="Download recording" onClick={downloadRecording}>
          <Download size={18} />
        </button>
        <button
          type="button"
          className="icon-button"
          title="Export shareable clip"
          disabled={!snapshot || exportingClip}
          onClick={downloadShareableClip}
        >
          <Download size={18} />
        </button>
      </section>

      <section className="timeline-band">
        <div className="timeline-head">
          <span>Sequence {sequence}</span>
          <span>{events.length} events</span>
        </div>
        <input
          type="range"
          min={0}
          max={snapshot?.last_sequence ?? 0}
          value={sequence}
          onChange={(event) => setSequence(Number(event.target.value))}
        />
        <div className="event-rail">
          {events.map((event) => (
            <button
              key={event.sequence}
              type="button"
              className={event.sequence <= sequence ? "event-dot seen" : "event-dot"}
              title={`${event.sequence} ${event.kind}`}
              onClick={() => {
                setSequence(event.sequence);
                setSelectedEventSequence(event.sequence);
              }}
            />
          ))}
        </div>
      </section>

      <section className="workspace">
        <TierMap
          memories={visibleMemories}
          activeEvent={activeEvent}
          selectedId={selectedId}
          contestedIds={contestedIds}
          onSelect={setSelectedId}
        />
        <div className="side-stack">
          <WhyPanel memory={selectedMemory} trace={whyTrace} challenge={selectedChallenge} />
          <DrilldownPanel
            event={selectedEvent}
            rawEvent={rawEvent}
            memory={selectedMemory}
            audit={auditDetail}
            trace={whyTrace}
            onSelect={setSelectedId}
          />
        </div>
      </section>

      <section className="lower-grid">
        <nav className="tabs" aria-label="Tideline views">
          <button className={activeView === "moment" ? "active" : ""} onClick={() => setActiveView("moment")}>
            <Activity size={16} /> Moment
          </button>
          <button
            className={activeView === "staleness" ? "active" : ""}
            onClick={() => setActiveView("staleness")}
          >
            <ShieldCheck size={16} /> Staleness
          </button>
          <button
            className={activeView === "consolidation" ? "active" : ""}
            onClick={() => setActiveView("consolidation")}
          >
            <GitCompareArrows size={16} /> Consolidation
          </button>
          <button className={activeView === "poisoning" ? "active" : ""} onClick={() => setActiveView("poisoning")}>
            <ShieldAlert size={16} /> Poisoning
          </button>
          <button className={activeView === "bitemporal" ? "active" : ""} onClick={() => setActiveView("bitemporal")}>
            <RefreshCcw size={16} /> Bi-temporal
          </button>
          <button className={activeView === "graph" ? "active" : ""} onClick={() => setActiveView("graph")}>
            <Waypoints size={16} /> Graph
          </button>
          <button className={activeView === "diff" ? "active" : ""} onClick={() => setActiveView("diff")}>
            <GitCompareArrows size={16} /> Diff
          </button>
        </nav>
        {activeView === "moment" && <MomentView events={momentEvents} memories={visibleMemories} />}
        {activeView === "staleness" && (
          <StalenessView
            decisions={stalenessDecisions}
            selectedId={selectedId}
            trace={whyTrace}
            onSelect={setSelectedId}
          />
        )}
        {activeView === "consolidation" && (
          <ConsolidationView events={consolidationEvents} memories={visibleMemories} />
        )}
        {activeView === "poisoning" && <PoisoningView memories={visibleMemories} lowCredence={lowCredence} />}
        {activeView === "bitemporal" && <BiTemporalView memories={visibleMemories} asOf={asOf} />}
        {activeView === "graph" && <GraphView snapshot={snapshot} selectedId={selectedId} onSelect={setSelectedId} />}
        {activeView === "diff" && (
          <DiffView
            snapshot={snapshot}
            fromSequence={diffFrom}
            toSequence={diffTo}
            maxSequence={maxSequence}
            onFromChange={setDiffFrom}
            onToChange={setDiffTo}
          />
        )}
      </section>
    </main>
  );
}

function DrilldownPanel({
  event,
  rawEvent,
  memory,
  audit,
  trace,
  onSelect,
}: {
  event: TidelineEvent | null;
  rawEvent: EventRecordDetail | null;
  memory: MemoryItem | null;
  audit: AuditDetail | null;
  trace: WhyTrace | null;
  onSelect: (id: string) => void;
}) {
  const eventRecords = audit?.events ?? [];
  const humanEvents = eventRecords.filter((record) => record.kind === "human_signal");
  const matchingRecord = eventRecords.find((record) => record.sequence === event?.sequence) ?? rawEvent;
  const afterState = event?.tier_to ?? (event?.valid_to_unix ? "closed" : memory?.tier ?? "unknown");

  return (
    <section className="panel drilldown-panel">
      <div className="panel-title">
        <h2>Drilldown</h2>
        <span>{event ? `#${event.sequence}` : "none"}</span>
      </div>
      {event ? (
        <>
          <div className="event-card">
            <strong>{event.human_signal_action ?? event.consolidation_action ?? event.kind}</strong>
            <span>{formatUnix(event.recorded_at_unix)}</span>
            <div className="id-list">
              {event.memory_ids.map((id) => (
                <button key={id} type="button" onClick={() => onSelect(id)}>
                  {shortId(id)}
                </button>
              ))}
            </div>
          </div>
          <div className="transition-grid">
            <div>
              <b>Before</b>
              <span>{event.tier_from ?? memory?.tier ?? "unknown"}</span>
            </div>
            <div>
              <b>After</b>
              <span>{afterState}</span>
            </div>
          </div>
          {memory ? (
            <div className="provenance-chain">
              <b>{memory.provenance.source_kind}</b>
              <span>{memory.provenance.source_ref ?? "no source ref"}</span>
              <em>{memory.provenance.ingested_by}</em>
            </div>
          ) : null}
          {event.consolidation_evidence.length > 0 ? (
            <div className="compact-evidence">
              {event.consolidation_evidence.map((evidence) => (
                <span key={`${event.sequence}-${evidence.memory_id}`}>
                  {shortId(evidence.memory_id)} {evidence.significance.toFixed(2)}
                </span>
              ))}
            </div>
          ) : null}
          {humanEvents.length > 0 ? (
            <ol className="audit-list compact-audit">
              {humanEvents.slice(-4).map((record) => (
                <li key={record.sequence}>
                  #{record.sequence} {humanSignalSummary(record)}
                </li>
              ))}
            </ol>
          ) : null}
          <pre className="raw-json">{JSON.stringify(matchingRecord?.event ?? event, null, 2)}</pre>
          {trace ? (
            <div className="linked-why">
              <span>{trace.currency_state}</span>
              <span>{trace.significance.final_score.toFixed(3)}</span>
              <span>{trace.audit_trail.length} audit</span>
            </div>
          ) : null}
        </>
      ) : (
        <p className="empty">No event selected</p>
      )}
    </section>
  );
}

function TierMap({
  memories,
  activeEvent,
  selectedId,
  contestedIds,
  onSelect,
}: {
  memories: MemoryItem[];
  activeEvent: TidelineEvent | null;
  selectedId: string | null;
  contestedIds: Set<string>;
  onSelect: (id: string) => void;
}) {
  const width = 760;
  const height = 430;

  return (
    <section className="panel tier-panel">
      <div className="panel-title">
        <h2>Tier Map</h2>
        <span>{memories.length}</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Memory tier map">
        {tierLabels.map((tier, index) => (
          <g key={tier}>
            <line x1={140 + index * 240} x2={140 + index * 240} y1={44} y2={390} className="tier-line" />
            <text x={140 + index * 240} y={28} textAnchor="middle" className="tier-label">
              {tier}
            </text>
          </g>
        ))}
        {memories.map((memory, index) => {
          const tierIndex = tierOrder[memory.tier] ?? 1;
          const x = 140 + tierIndex * 240 + ((index % 5) - 2) * 16;
          const y = 374 - Math.max(0.04, Math.min(1, memory.significance)) * 292;
          const active = activeEvent?.memory_ids.includes(memory.id) ?? false;
          const contested = contestedIds.has(memory.id);

          return (
            <g key={memory.id} className="node-hit" onClick={() => onSelect(memory.id)}>
              <circle
                cx={x}
                cy={y}
                r={selectedId === memory.id ? 18 : 14}
                className={`memory-node ${memory.tier} ${active ? "pulse" : ""} ${contested ? "contested" : ""}`}
              />
              <text x={x} y={y + 34} textAnchor="middle" className="node-label">
                {memoryLabel(memory.content)}
              </text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}

function WhyPanel({
  memory,
  trace,
  challenge,
}: {
  memory: MemoryItem | null;
  trace: WhyTrace | null;
  challenge: ChallengeNote | null;
}) {
  const bars = trace
    ? [
        ["base", trace.significance.base_score],
        ["decay", trace.significance.decay_multiplier],
        ["reinforcement", trace.significance.reinforcement],
        ["outcome", trace.significance.outcome_bonus],
        ["contradiction", trace.significance.contradiction_penalty],
        ["graph", trace.significance.graph_centrality],
        ["final", trace.significance.final_score],
      ]
    : [];
  const max = Math.max(1, ...bars.map(([, value]) => Math.abs(Number(value))));

  return (
    <section className="panel why-panel">
      <div className="panel-title">
        <h2>Why</h2>
        <span>{trace?.currency_state ?? "none"}</span>
      </div>
      {memory ? (
        <>
          <p className="memory-content">{memory.content}</p>
          <div className="meta-grid">
            <span>{memory.tier}</span>
            <span>{memory.credence}</span>
            <span>{memory.significance.toFixed(3)}</span>
          </div>
          {challenge ? (
            <div className="human-signal-note">
              <strong>Challenge</strong>
              <span>{challenge.reason}</span>
              <em>{challenge.actor}</em>
            </div>
          ) : null}
          <div className="bar-stack">
            {bars.map(([label, value]) => (
              <div className="bar-row" key={label}>
                <span>{label}</span>
                <div>
                  <i style={{ width: `${(Math.abs(Number(value)) / max) * 100}%` }} />
                </div>
                <b>{Number(value).toFixed(3)}</b>
              </div>
            ))}
          </div>
          <ol className="audit-list">
            {(trace?.audit_trail ?? []).slice(-5).map((entry) => (
              <li key={entry}>{entry}</li>
            ))}
          </ol>
        </>
      ) : (
        <p className="empty">No memory selected</p>
      )}
    </section>
  );
}

function MomentView({ events, memories }: { events: TidelineEvent[]; memories: MemoryItem[] }) {
  const byId = new Map(memories.map((memory) => [memory.id, memory]));

  return (
    <section className="panel wide-panel">
      <div className="panel-title">
        <h2>Shibahama Moment</h2>
        <span>{events.length}</span>
      </div>
      <div className="moment-lanes">
        {events.length === 0 ? <p className="empty">No invalidation or reconstruction events</p> : null}
        {events.map((event) => (
          <article key={event.sequence} className="moment-row">
            <strong>{event.human_signal_action ?? event.kind}</strong>
            <span>#{event.sequence}</span>
            <p>
              {event.memory_ids.map((id) => byId.get(id)?.content ?? id).join(" -> ")}
              {event.human_signal_reason ? `: ${event.human_signal_reason}` : ""}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function StalenessView({
  decisions,
  selectedId,
  trace,
  onSelect,
}: {
  decisions: StalenessDecision[];
  selectedId: string | null;
  trace: WhyTrace | null;
  onSelect: (id: string) => void;
}) {
  return (
    <section className="panel wide-panel staleness-panel">
      <div className="panel-title">
        <h2>Stale Answer Avoided</h2>
        <span>{decisions.length}</span>
      </div>
      {decisions.length === 0 ? <p className="empty">No supersession decisions</p> : null}
      <div className="staleness-list">
        {decisions.map((decision) => {
          const rowIds = new Set(
            [decision.superseded.id, decision.current?.id].filter((id): id is string => Boolean(id)),
          );
          const rowTrace = trace && rowIds.has(trace.item.id) ? trace : null;

          return (
            <article key={`${decision.event.sequence}-${decision.superseded.id}`} className="staleness-row">
              <div className="staleness-head">
                <strong>{decision.event.kind}</strong>
                <span>#{decision.event.sequence}</span>
                <span>{formatUnix(decision.event.recorded_at_unix)}</span>
              </div>
              <div className="staleness-compare">
                <StalenessMemoryCard
                  label="Superseded"
                  memory={decision.superseded}
                  selected={selectedId === decision.superseded.id}
                  onSelect={onSelect}
                />
                <div className="decision-arrow">{"->"}</div>
                {decision.current ? (
                  <StalenessMemoryCard
                    label="Current"
                    memory={decision.current}
                    selected={selectedId === decision.current.id}
                    onSelect={onSelect}
                  />
                ) : (
                  <div className="staleness-memory missing">
                    <span className="staleness-memory-label">Current</span>
                    <span className="staleness-memory-content">No replacement in snapshot</span>
                  </div>
                )}
              </div>
              <div className="staleness-facts">
                <span>
                  <b>cutoff</b>
                  {formatUnixMaybe(decision.cutoffUnix)}
                </span>
                <span>
                  <b>stale credence</b>
                  {decision.superseded.credence}
                </span>
                <span>
                  <b>current credence</b>
                  {decision.current?.credence ?? "n/a"}
                </span>
                <span>
                  <b>current valid</b>
                  {decision.current ? validWindow(decision.current) : "n/a"}
                </span>
              </div>
              {rowTrace ? (
                <div className="staleness-why">
                  <div>
                    <b>why trace</b>
                    <span>{rowTrace.currency_state}</span>
                    <span>{rowTrace.significance.final_score.toFixed(3)}</span>
                    <span>{validWindow(rowTrace.item)}</span>
                  </div>
                  {rowTrace.audit_trail.length > 0 ? (
                    <ol>
                      {rowTrace.audit_trail.slice(-3).map((entry) => (
                        <li key={entry}>{entry}</li>
                      ))}
                    </ol>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function StalenessMemoryCard({
  label,
  memory,
  selected,
  onSelect,
}: {
  label: string;
  memory: MemoryItem;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className={selected ? "staleness-memory selected" : "staleness-memory"}
      onClick={() => onSelect(memory.id)}
    >
      <span className="staleness-memory-label">{label}</span>
      <span className="staleness-memory-content">{memory.content}</span>
      <span className="staleness-memory-meta">
        {memory.credence} / {memory.tier} / {memory.significance.toFixed(3)}
      </span>
      <span className="staleness-memory-meta">{validWindow(memory)}</span>
    </button>
  );
}

function ConsolidationView({
  events,
  memories,
}: {
  events: TidelineEvent[];
  memories: MemoryItem[];
}) {
  const byId = new Map(memories.map((memory) => [memory.id, memory]));

  return (
    <section className="panel wide-panel consolidation-panel">
      <div className="panel-title">
        <h2>Consolidation</h2>
        <span>{events.length}</span>
      </div>
      {events.length === 0 ? <p className="empty">No consolidation decisions</p> : null}
      <div className="consolidation-list">
        {events.map((event) => {
          const outputId =
            event.consolidation_action === "merge" ? event.memory_ids.at(-1) ?? null : null;
          const inputIds =
            outputId === null ? event.memory_ids : event.memory_ids.filter((id) => id !== outputId);

          return (
            <article key={event.sequence} className={`consolidation-row ${event.consolidation_action ?? "unknown"}`}>
              <div className="consolidation-main">
                <strong>{event.consolidation_action ?? "decision"}</strong>
                <span>#{event.sequence}</span>
                <p>{event.consolidation_why ?? "No why trace recorded"}</p>
              </div>
              <div className="merge-flow">
                <div>
                  {inputIds.map((id) => (
                    <span key={id}>{byId.get(id)?.content ? memoryLabel(byId.get(id)!.content) : shortId(id)}</span>
                  ))}
                </div>
                <b>{"->"}</b>
                <div>
                  {outputId ? (
                    <span>{byId.get(outputId)?.content ? memoryLabel(byId.get(outputId)!.content) : shortId(outputId)}</span>
                  ) : (
                    <span>{event.tier_to ?? event.consolidation_action}</span>
                  )}
                </div>
              </div>
              <div className="evidence-grid">
                {event.consolidation_evidence.map((evidence) => (
                  <div key={`${event.sequence}-${evidence.memory_id}`} className="evidence-cell">
                    <span>{byId.get(evidence.memory_id)?.content ? memoryLabel(byId.get(evidence.memory_id)!.content) : shortId(evidence.memory_id)}</span>
                    <b>{evidence.significance.toFixed(2)}</b>
                    <i>
                      {evidence.actual_use_count}/{evidence.access_count}
                    </i>
                    <em>{evidence.credence_floor}</em>
                  </div>
                ))}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PoisoningView({
  memories,
  lowCredence,
}: {
  memories: MemoryItem[];
  lowCredence: MemoryItem[];
}) {
  const authoritative = memories.filter((memory) => !lowCredence.includes(memory));

  return (
    <section className="panel wide-panel poisoning-grid">
      <div className="lane">
        <h2>Quarantine</h2>
        {lowCredence.map((memory) => (
          <p key={memory.id}>{memory.content}</p>
        ))}
      </div>
      <div className="wall" />
      <div className="lane">
        <h2>Recallable Authority</h2>
        {authoritative.map((memory) => (
          <p key={memory.id}>{memory.content}</p>
        ))}
      </div>
    </section>
  );
}

function BiTemporalView({ memories, asOf }: { memories: MemoryItem[]; asOf: string }) {
  return (
    <section className="panel wide-panel">
      <div className="panel-title">
        <h2>Bi-temporal State</h2>
        <span>{asOf || "current"}</span>
      </div>
      <div className="time-table">
        {memories.map((memory) => (
          <div key={memory.id} className="time-row">
            <span>{memoryLabel(memory.content)}</span>
            <i style={{ left: `${timeOffset(memory.valid_from_unix)}%`, width: `${timeWidth(memory)}%` }} />
            <b>{memory.valid_to_unix ? "closed" : "open"}</b>
          </div>
        ))}
      </div>
    </section>
  );
}

function GraphView({
  snapshot,
  selectedId,
  onSelect,
}: {
  snapshot: TidelineSnapshot | null;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const nodes = snapshot?.graph.nodes ?? [];
  const edges = snapshot?.graph.edges ?? [];
  const width = 940;
  const height = 330;
  const positions = new Map(
    nodes.map((node, index) => {
      const angle = (index / Math.max(1, nodes.length)) * Math.PI * 2;
      return [
        node.id,
        {
          x: width / 2 + Math.cos(angle) * 330,
          y: height / 2 + Math.sin(angle) * 108,
        },
      ];
    }),
  );

  return (
    <section className="panel wide-panel">
      <div className="panel-title">
        <h2>Graph</h2>
        <span>{edges.length} edges</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="graph-svg" role="img" aria-label="Memory graph">
        {edges.map((edge) => {
          const from = positions.get(edge.from);
          const to = positions.get(edge.to);

          if (!from || !to) {
            return null;
          }

          return (
            <line key={edge.id} x1={from.x} y1={from.y} x2={to.x} y2={to.y} className="graph-edge" />
          );
        })}
        {nodes.map((node) => {
          const position = positions.get(node.id);

          if (!position) {
            return null;
          }

          return (
            <g key={node.id} onClick={() => onSelect(node.id)} className="node-hit">
              <circle
                cx={position.x}
                cy={position.y}
                r={selectedId === node.id ? 18 : 13}
                className={`memory-node ${node.tier}`}
              />
              <text x={position.x} y={position.y + 32} textAnchor="middle" className="node-label">
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>
    </section>
  );
}

function DiffView({
  snapshot,
  fromSequence,
  toSequence,
  maxSequence,
  onFromChange,
  onToChange,
}: {
  snapshot: TidelineSnapshot | null;
  fromSequence: number;
  toSequence: number;
  maxSequence: number;
  onFromChange: (sequence: number) => void;
  onToChange: (sequence: number) => void;
}) {
  const diff = useMemo(
    () => buildSessionDiff(snapshot, fromSequence, toSequence),
    [fromSequence, snapshot, toSequence],
  );

  return (
    <section className="panel wide-panel diff-panel">
      <div className="panel-title">
        <h2>Session Diff</h2>
        <span>
          {diff.start} {"->"} {diff.end}
        </span>
      </div>
      <div className="diff-controls">
        <label>
          From
          <input
            type="range"
            min={0}
            max={maxSequence}
            value={fromSequence}
            onChange={(event) => onFromChange(Number(event.target.value))}
          />
          <span>{fromSequence}</span>
        </label>
        <label>
          To
          <input
            type="range"
            min={0}
            max={maxSequence}
            value={toSequence}
            onChange={(event) => onToChange(Number(event.target.value))}
          />
          <span>{toSequence}</span>
        </label>
      </div>
      <div className="diff-summary">
        <span>
          Known {diff.knownAtStart} {"->"} {diff.knownAtEnd}
        </span>
        <span>
          Active {diff.activeAtStart} {"->"} {diff.activeAtEnd}
        </span>
        <span>{diff.events.length} events</span>
        <span>{diff.graphChanges.length} graph changes</span>
      </div>
      <div className="diff-grid">
        <DiffColumn title="New Memories" empty="No new memories">
          {diff.addedMemories.map((memory) => (
            <p key={memory}>{memory}</p>
          ))}
        </DiffColumn>
        <DiffColumn title="State Changes" empty="No invalidations or reconstructions">
          {diff.stateChanges.map((event) => (
            <p key={event.sequence}>
              <strong>#{event.sequence}</strong> {event.kind} {event.memoryLabels.join(" -> ")}
            </p>
          ))}
        </DiffColumn>
        <DiffColumn title="Tier Moves" empty="No tier changes">
          {diff.tierChanges.map((event) => (
            <p key={event.sequence}>
              <strong>#{event.sequence}</strong> {event.memoryLabels[0]} {event.tier_from ?? "?"} {"->"}{" "}
              {event.tier_to ?? "?"}
            </p>
          ))}
        </DiffColumn>
        <DiffColumn title="Accesses" empty="No access events">
          {diff.accesses.map((event) => (
            <p key={event.sequence}>
              <strong>#{event.sequence}</strong> {event.memoryLabels[0]} {event.access_outcome ?? "surfaced"}
            </p>
          ))}
        </DiffColumn>
      </div>
    </section>
  );
}

function DiffColumn({
  title,
  empty,
  children,
}: {
  title: string;
  empty: string;
  children: React.ReactNode;
}) {
  const hasChildren = React.Children.count(children) > 0;

  return (
    <div className="diff-column">
      <h2>{title}</h2>
      {hasChildren ? children : <p className="empty">{empty}</p>}
    </div>
  );
}

async function renderShareableClip(snapshot: TidelineSnapshot) {
  if (typeof MediaRecorder === "undefined") {
    throw new Error("clip export unavailable");
  }

  const width = 960;
  const height = 540;
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");

  if (!context || !canvas.captureStream) {
    throw new Error("canvas export unavailable");
  }

  const stream = canvas.captureStream(12);
  const recorder = new MediaRecorder(stream, recorderOptions());
  const chunks: BlobPart[] = [];
  const done = new Promise<Blob>((resolve, reject) => {
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    recorder.onerror = () => reject(new Error("clip recording failed"));
    recorder.onstop = () => {
      resolve(
        new Blob(chunks, {
          type: recorder.mimeType || "video/webm",
        }),
      );
    };
  });
  const sequences = sampledClipSequences(snapshot);
  let stopped = false;

  try {
    recorder.start();

    for (const sequence of sequences) {
      drawClipFrame(context, snapshot, sequence, width, height);
      await wait(220);
    }

    if (sequences.length <= 1) {
      await wait(300);
    }

    recorder.stop();
    stopped = true;

    return await done;
  } finally {
    if (!stopped && recorder.state !== "inactive") {
      recorder.stop();
    }

    for (const track of stream.getTracks()) {
      track.stop();
    }
  }
}

function recorderOptions(): MediaRecorderOptions | undefined {
  for (const mimeType of ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"]) {
    if (MediaRecorder.isTypeSupported(mimeType)) {
      return { mimeType };
    }
  }

  return undefined;
}

function sampledClipSequences(snapshot: TidelineSnapshot) {
  const sequences = [
    0,
    ...snapshot.events.map((event) => event.sequence),
    snapshot.last_sequence ?? 0,
  ]
    .filter((sequence, index, all) => all.indexOf(sequence) === index)
    .sort((left, right) => left - right);
  const maxFrames = 48;

  if (sequences.length <= maxFrames) {
    return sequences;
  }

  return Array.from({ length: maxFrames }, (_, index) => {
    const sourceIndex = Math.round((index / (maxFrames - 1)) * (sequences.length - 1));
    return sequences[sourceIndex];
  }).filter((sequence, index, all) => all.indexOf(sequence) === index);
}

function drawClipFrame(
  context: CanvasRenderingContext2D,
  snapshot: TidelineSnapshot,
  sequence: number,
  width: number,
  height: number,
) {
  const events = snapshot.events;
  const activeEvent =
    [...events].reverse().find((event) => event.sequence <= sequence) ?? null;
  const memories = snapshot.memories.filter(
    (memory) => firstMemorySequence(events, memory.id) <= sequence,
  );

  context.fillStyle = "#f4f0e8";
  context.fillRect(0, 0, width, height);
  context.fillStyle = "rgba(34, 109, 104, 0.08)";
  for (let x = 0; x < width; x += 42) {
    context.fillRect(x, 0, 1, height);
  }
  for (let y = 0; y < height; y += 42) {
    context.fillRect(0, y, width, 1);
  }

  context.fillStyle = "#20211f";
  context.font = "700 34px Inter, sans-serif";
  context.fillText("Tideline", 32, 52);
  context.font = "700 15px Inter, sans-serif";
  context.fillStyle = "#226d68";
  context.fillText(snapshot.namespace, 34, 82);
  context.fillStyle = "#5a564f";
  context.fillText(`Sequence ${sequence}`, width - 180, 52);
  context.fillText(activeEvent ? activeEvent.kind : "start", width - 180, 78);

  for (const [index, tier] of tierLabels.entries()) {
    const x = 170 + index * 310;
    context.strokeStyle = "#d8d0c1";
    context.lineWidth = 2;
    context.setLineDash([6, 10]);
    context.beginPath();
    context.moveTo(x, 112);
    context.lineTo(x, 470);
    context.stroke();
    context.setLineDash([]);
    context.fillStyle = "#4c4942";
    context.font = "800 16px Inter, sans-serif";
    context.textAlign = "center";
    context.fillText(tier, x, 104);
  }

  for (const [index, memory] of memories.entries()) {
    const state = memoryStateAtSequence(memory, events, sequence);
    const tierIndex = tierOrder[state.tier] ?? 1;
    const x = 170 + tierIndex * 310 + ((index % 5) - 2) * 22;
    const y = 450 - Math.max(0.04, Math.min(1, memory.significance)) * 300;
    const active = activeEvent?.memory_ids.includes(memory.id) ?? false;

    context.globalAlpha = state.invalidated ? 0.38 : 1;
    context.fillStyle = tierColor(state.tier);
    context.strokeStyle = active ? "#20211f" : "#fffdf8";
    context.lineWidth = active ? 5 : 3;
    context.beginPath();
    context.arc(x, y, active ? 18 : 14, 0, Math.PI * 2);
    context.fill();
    context.stroke();
    context.fillStyle = "#3d3a34";
    context.font = "700 12px Inter, sans-serif";
    context.textAlign = "center";
    context.fillText(memoryLabel(memory.content), x, y + 34, 148);
    context.globalAlpha = 1;
  }

  context.textAlign = "left";
}

function firstMemorySequence(events: TidelineEvent[], id: string) {
  const first = events.find(
    (event) =>
      (event.kind === "memory_written" || event.kind === "demo_step") &&
      event.memory_ids.includes(id),
  );

  return first?.sequence ?? 0;
}

function memoryStateAtSequence(memory: MemoryItem, events: TidelineEvent[], sequence: number) {
  let tier = memory.tier;
  let invalidated = false;

  for (const event of events) {
    if (event.sequence > sequence || !event.memory_ids.includes(memory.id)) {
      continue;
    }

    if ((event.kind === "memory_written" || event.kind === "tier_changed") && event.tier_to) {
      tier = event.tier_to;
    }

    if (event.kind === "content_compacted") {
      tier = "cold";
    }

    if (event.kind === "memory_invalidated") {
      invalidated = true;
    }

    if (event.kind === "reconstruction_applied") {
      invalidated = event.memory_ids[0] === memory.id;
    }
  }

  return { tier, invalidated };
}

function tierColor(tier: Tier) {
  if (tier === "hot") {
    return "#cf4f3f";
  }

  if (tier === "cold") {
    return "#3a8d95";
  }

  return "#d9a441";
}

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function memoryLabel(content: string) {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > 28 ? `${normalized.slice(0, 25)}...` : normalized;
}

function buildStalenessDecisions(events: TidelineEvent[], memories: MemoryItem[]) {
  const byId = new Map(memories.map((memory) => [memory.id, memory]));
  const decisions: StalenessDecision[] = [];
  const reconstructedSupersededIds = new Set<string>();

  for (const event of events) {
    if (event.kind !== "reconstruction_applied") {
      continue;
    }

    const superseded = byId.get(event.memory_ids[0] ?? "");

    if (!superseded) {
      continue;
    }

    const current = byId.get(event.memory_ids[1] ?? "") ?? findCurrentReplacement(superseded, event, memories);
    reconstructedSupersededIds.add(superseded.id);
    decisions.push({
      event,
      superseded,
      current,
      cutoffUnix: event.valid_to_unix ?? superseded.valid_to_unix,
    });
  }

  for (const event of events) {
    if (event.kind !== "memory_invalidated") {
      continue;
    }

    const superseded = byId.get(event.memory_ids[0] ?? "");

    if (!superseded || reconstructedSupersededIds.has(superseded.id)) {
      continue;
    }

    decisions.push({
      event,
      superseded,
      current: findCurrentReplacement(superseded, event, memories),
      cutoffUnix: event.valid_to_unix ?? superseded.valid_to_unix,
    });
  }

  return decisions.sort((left, right) => right.event.sequence - left.event.sequence);
}

function findCurrentReplacement(
  superseded: MemoryItem,
  event: TidelineEvent,
  memories: MemoryItem[],
) {
  const cutoffUnix = event.valid_to_unix ?? superseded.valid_to_unix ?? event.recorded_at_unix;
  const candidates = memories
    .filter((memory) => memory.id !== superseded.id)
    .filter((memory) => memory.valid_to_unix === null)
    .filter((memory) => memory.valid_from_unix >= cutoffUnix)
    .sort((left, right) => left.valid_from_unix - right.valid_from_unix);
  const sameSource = candidates.filter(
    (memory) =>
      superseded.provenance.source_ref !== null &&
      memory.provenance.source_kind === superseded.provenance.source_kind &&
      memory.provenance.source_ref === superseded.provenance.source_ref,
  );

  return sameSource[0] ?? candidates[0] ?? null;
}

function buildSessionDiff(snapshot: TidelineSnapshot | null, fromSequence: number, toSequence: number) {
  const events = snapshot?.events ?? [];
  const memories = snapshot?.memories ?? [];
  const graphEdges = snapshot?.graph.edges ?? [];
  const labels = new Map(memories.map((memory) => [memory.id, memoryLabel(memory.content)]));
  const start = Math.min(fromSequence, toSequence);
  const end = Math.max(fromSequence, toSequence);
  const eventsInRange = events
    .filter((event) => event.sequence > start && event.sequence <= end)
    .map((event) => ({
      ...event,
      memoryLabels: event.memory_ids.map((id) => labels.get(id) ?? shortId(id)),
    }));
  const knownAtStart = knownMemoryIdsAt(events, start);
  const knownAtEnd = knownMemoryIdsAt(events, end);
  const activeAtStart = activeMemoryIdsAt(events, start);
  const activeAtEnd = activeMemoryIdsAt(events, end);
  const addedMemories = [...knownAtEnd]
    .filter((id) => !knownAtStart.has(id))
    .map((id) => labels.get(id) ?? shortId(id));
  const stateChanges = eventsInRange.filter((event) =>
    [
      "memory_invalidated",
      "reconstruction_applied",
      "reverification_flagged",
      "content_compacted",
      "consolidation_decision",
    ].includes(event.kind),
  );
  const tierChanges = eventsInRange.filter((event) => event.kind === "tier_changed");
  const accesses = eventsInRange.filter((event) => event.kind === "access_recorded");
  const graphChanges = graphEdges.filter((edge) => {
    const sequence = sequenceFromGraphEdge(edge.id);
    return sequence !== null && sequence > start && sequence <= end;
  });

  return {
    start,
    end,
    events: eventsInRange,
    knownAtStart: knownAtStart.size,
    knownAtEnd: knownAtEnd.size,
    activeAtStart: activeAtStart.size,
    activeAtEnd: activeAtEnd.size,
    addedMemories,
    stateChanges,
    tierChanges,
    accesses,
    graphChanges,
  };
}

function knownMemoryIdsAt(events: TidelineEvent[], sequence: number) {
  const ids = new Set<string>();

  for (const event of events) {
    if (event.sequence > sequence) {
      continue;
    }

    if (event.kind === "memory_written" || event.kind === "demo_step") {
      for (const id of event.memory_ids) {
        ids.add(id);
      }
    }
  }

  return ids;
}

function activeMemoryIdsAt(events: TidelineEvent[], sequence: number) {
  const ids = knownMemoryIdsAt(events, sequence);

  for (const event of events) {
    if (event.sequence > sequence) {
      continue;
    }

    if (event.kind === "memory_invalidated") {
      ids.delete(event.memory_ids[0]);
    }

    if (event.kind === "reconstruction_applied") {
      ids.delete(event.memory_ids[0]);
      if (event.memory_ids[1]) {
        ids.add(event.memory_ids[1]);
      }
    }
  }

  return ids;
}

function sequenceFromGraphEdge(id: string) {
  const match = /^event-(\d+)-/.exec(id);
  return match ? Number(match[1]) : null;
}

function shortId(id: string) {
  return id.length > 12 ? `${id.slice(0, 8)}...` : id;
}

function formatUnix(unix: number) {
  return new Date(unix * 1000).toLocaleString();
}

function formatUnixMaybe(unix: number | null | undefined) {
  return unix === null || unix === undefined ? "open" : formatUnix(unix);
}

function validWindow(memory: MemoryItem) {
  return `${formatUnix(memory.valid_from_unix)} -> ${formatUnixMaybe(memory.valid_to_unix)}`;
}

function humanSignalSummary(record: EventRecordDetail) {
  const raw = JSON.stringify(record.event);
  return raw.length > 96 ? `${raw.slice(0, 93)}...` : raw;
}

function timeOffset(unix: number) {
  return Math.max(0, Math.min(92, ((unix % 86400) / 86400) * 92));
}

function timeWidth(memory: MemoryItem) {
  if (!memory.valid_to_unix) {
    return 18;
  }

  return Math.max(8, Math.min(90, ((memory.valid_to_unix - memory.valid_from_unix) / 86400) * 12));
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
