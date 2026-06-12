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

type ViewName = "moment" | "poisoning" | "bitemporal" | "graph" | "diff";

const API_BASE = "http://127.0.0.1:8765";
const tierOrder: Record<string, number> = { hot: 0, warm: 1, cold: 2 };
const tierLabels = ["hot", "warm", "cold"];

function App() {
  const [baseUrl, setBaseUrl] = useState(API_BASE);
  const [apiKey, setApiKey] = useState("");
  const [namespace, setNamespace] = useState("default");
  const [snapshot, setSnapshot] = useState<TidelineSnapshot | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [whyTrace, setWhyTrace] = useState<WhyTrace | null>(null);
  const [status, setStatus] = useState("idle");
  const [live, setLive] = useState(false);
  const [activeView, setActiveView] = useState<ViewName>("moment");
  const [sequence, setSequence] = useState<number>(0);
  const [diffFrom, setDiffFrom] = useState<number>(0);
  const [diffTo, setDiffTo] = useState<number>(0);
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
    const lastSequence = data.last_sequence ?? 0;
    setSnapshot(data);
    setSequence(lastSequence);
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
      return;
    }

    loadWhy(selectedId).catch(() => setWhyTrace(null));
  }, [loadWhy, selectedId]);

  const events = snapshot?.events ?? [];
  const maxSequence = snapshot?.last_sequence ?? 0;
  const visibleEvents = events.filter((event) => event.sequence <= sequence);
  const activeEvent = visibleEvents.at(-1) ?? null;
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
  const selectedMemory = visibleMemories.find((memory) => memory.id === selectedId) ?? null;
  const lowCredence = visibleMemories.filter((memory) =>
    ["unverified", "model_inferred"].includes(memory.credence),
  );
  const momentEvents = visibleEvents.filter((event) =>
    ["memory_invalidated", "reconstruction_applied"].includes(event.kind),
  );

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
              onClick={() => setSequence(event.sequence)}
            />
          ))}
        </div>
      </section>

      <section className="workspace">
        <TierMap
          memories={visibleMemories}
          activeEvent={activeEvent}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <WhyPanel memory={selectedMemory} trace={whyTrace} />
      </section>

      <section className="lower-grid">
        <nav className="tabs" aria-label="Tideline views">
          <button className={activeView === "moment" ? "active" : ""} onClick={() => setActiveView("moment")}>
            <Activity size={16} /> Moment
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

function TierMap({
  memories,
  activeEvent,
  selectedId,
  onSelect,
}: {
  memories: MemoryItem[];
  activeEvent: TidelineEvent | null;
  selectedId: string | null;
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

          return (
            <g key={memory.id} className="node-hit" onClick={() => onSelect(memory.id)}>
              <circle
                cx={x}
                cy={y}
                r={selectedId === memory.id ? 18 : 14}
                className={`memory-node ${memory.tier} ${active ? "pulse" : ""}`}
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

function WhyPanel({ memory, trace }: { memory: MemoryItem | null; trace: WhyTrace | null }) {
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
            <strong>{event.kind}</strong>
            <span>#{event.sequence}</span>
            <p>{event.memory_ids.map((id) => byId.get(id)?.content ?? id).join(" -> ")}</p>
          </article>
        ))}
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

function memoryLabel(content: string) {
  const normalized = content.replace(/\s+/g, " ").trim();
  return normalized.length > 28 ? `${normalized.slice(0, 25)}...` : normalized;
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
    ["memory_invalidated", "reconstruction_applied", "reverification_flagged", "content_compacted"].includes(
      event.kind,
    ),
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
