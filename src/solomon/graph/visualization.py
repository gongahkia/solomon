# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem
from solomon.graph.models import DependencyEdge, EdgeType
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.types import KnowledgeStoreProtocol

GraphFormat = Literal["mermaid", "dot"]


class DependencyGraphNode(SolomonModel):
    id: str
    label: str
    kind: Literal["knowledge_item", "external_authority"]


class DependencyGraphView(SolomonModel):
    nodes: list[DependencyGraphNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)


def dependency_graph_view(
    *,
    graph: DependencyGraphProtocol,
    store: KnowledgeStoreProtocol,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> DependencyGraphView:
    items = store.get_many(matter_id=matter_id, client_id=client_id)
    item_by_id = {item.id: item for item in items}
    edges = graph.subgraph_for_items(item_by_id)
    nodes: dict[str, DependencyGraphNode] = {}

    for item in items:
        nodes[_node_key("knowledge_item", item.id)] = DependencyGraphNode(
            id=item.id,
            label=_item_label(item),
            kind="knowledge_item",
        )

    for edge in edges:
        if edge.source_id in item_by_id:
            nodes.setdefault(
                _node_key("knowledge_item", edge.source_id),
                DependencyGraphNode(
                    id=edge.source_id,
                    label=_item_label(item_by_id[edge.source_id]),
                    kind="knowledge_item",
                ),
            )
        if edge.target_kind == "knowledge_item" and edge.target_id in item_by_id:
            nodes.setdefault(
                _node_key("knowledge_item", edge.target_id),
                DependencyGraphNode(
                    id=edge.target_id,
                    label=_item_label(item_by_id[edge.target_id]),
                    kind="knowledge_item",
                ),
            )
        if edge.target_kind == "external_authority":
            nodes.setdefault(
                _node_key("external_authority", edge.target_id),
                DependencyGraphNode(
                    id=edge.target_id,
                    label=edge.target_id,
                    kind="external_authority",
                ),
            )

    return DependencyGraphView(
        nodes=sorted(nodes.values(), key=lambda node: (node.kind, node.label, node.id)),
        edges=sorted(edges, key=lambda edge: (edge.target_id, edge.source_id, edge.id)),
    )


def render_dependency_graph(view: DependencyGraphView, *, output_format: GraphFormat = "mermaid") -> str:
    if output_format == "mermaid":
        return render_mermaid(view)
    if output_format == "dot":
        return render_dot(view)
    raise ValueError(f"unsupported graph format: {output_format}")


def render_mermaid(view: DependencyGraphView) -> str:
    lines = [
        "flowchart LR",
        "  classDef authority fill:#f8fafc,stroke:#475569,stroke-width:1px;",
        "  classDef item fill:#ecfeff,stroke:#0f766e,stroke-width:1px;",
    ]
    for node in view.nodes:
        node_id = _mermaid_id(node)
        label = _escape_mermaid_label(node.label)
        lines.append(f'  {node_id}["{label}"]:::{_mermaid_class(node.kind)}')
    for edge in view.edges:
        target = _mermaid_id_for(edge.target_kind, edge.target_id)
        source = _mermaid_id_for("knowledge_item", edge.source_id)
        label = _edge_label(edge)
        lines.append(f"  {target} -->|{label}| {source}")
    return "\n".join(lines) + "\n"


def render_dot(view: DependencyGraphView) -> str:
    lines = [
        "digraph SolomonDependencyGraph {",
        "  rankdir=LR;",
        '  node [fontname="Helvetica"];',
    ]
    for node in view.nodes:
        node_id = _dot_id(node.kind, node.id)
        shape = "hexagon" if node.kind == "external_authority" else "box"
        label = _escape_dot_label(node.label)
        lines.append(f'  "{node_id}" [label="{label}", shape={shape}];')
    for edge in view.edges:
        target = _dot_id(edge.target_kind, edge.target_id)
        source = _dot_id("knowledge_item", edge.source_id)
        label = _escape_dot_label(_edge_label(edge))
        lines.append(f'  "{target}" -> "{source}" [label="{label}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _item_label(item: KnowledgeItem) -> str:
    summary = " ".join(item.content.split())
    if len(summary) > 64:
        summary = f"{summary[:61]}..."
    return f"{item.kind.value}: {summary or item.id}"


def _edge_label(edge: DependencyEdge) -> str:
    if edge.edge_type is EdgeType.SUPERSEDES:
        return "superseded by"
    if edge.edge_type is EdgeType.INTERNAL_DEPENDS_ON_INTERNAL:
        return "relied on by"
    return "relied on by"


def _node_key(kind: str, node_id: str) -> str:
    return f"{kind}:{node_id}"


def _mermaid_class(kind: str) -> str:
    return "authority" if kind == "external_authority" else "item"


def _mermaid_id(node: DependencyGraphNode) -> str:
    return _mermaid_id_for(node.kind, node.id)


def _mermaid_id_for(kind: str, node_id: str) -> str:
    prefix = "authority" if kind == "external_authority" else "item"
    safe = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    if not safe or safe[0].isdigit():
        safe = f"_{safe}"
    return f"{prefix}_{safe}"


def _dot_id(kind: str, node_id: str) -> str:
    return _node_key(kind, node_id)


def _escape_mermaid_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_dot_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
