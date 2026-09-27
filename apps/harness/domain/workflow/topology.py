"""Bound Workflow topology read from MVP_Workflow_v5.drawio (delivery-method r18 §6.2).

This module only reads the frozen topology master; it adds no Node, Edge or Gate. Product identity is
the topologyNodeId / topologyEdgeId attribute and the node semantic type is the semanticType
attribute. draw.io mxCell ids are drawing-tool internals: they are used to resolve edge endpoints and
then discarded, never exposed as identity.

An edge label, when the drawing carries one as a child cell of the edge, is the trigger wording shown
on that edge. Labels are presentation; the legal set at any position is always derived from the edge
structure, never from a label or from a table in this file.
"""
import xml.etree.ElementTree as ET

SEMANTIC_TYPES = (
    "HUMAN_ACTION", "ARTIFACT", "CONFIGURATION_DECISION", "APPLICABILITY_DECISION", "POLICY_DECISION",
    "RESULT_DECISION", "CONTROL_PLANE_ORCHESTRATOR", "ENGINEERING_MODULE", "REVIEW_MODULE", "HUMAN_GATE",
    "HUMAN_DECISION_OUTCOME", "TERMINAL_HUMAN_DECISION_OUTCOME",
)
PUBLISH_NODE = "N-PUBLISH"

# spec FR-26 wording for the decision each Human Gate edge carries. The legal decision set is derived
# from the bound topology; this table only supplies the normative display name and is itself checked
# against the topology (every Human Gate outgoing edge must have an entry).
SPEC_FR26_DECISION = {
    "E-D09": "Authorize & Freeze",
    "E-D12": "Continue",
    "E-D13": "Close Task",
    "E-D14": "Accept With reservation",
    "E-I11": "Continue",
    "E-I12": "Close Task",
    "E-V06": "Publish authorization",
    "E-V10": "Continue",
    "E-V11": "Close Task",
    "E-V12": "Accept With reservation",
}


class TopologyInvalid(Exception):
    """The bound topology cannot be read as a consistent node and edge registry."""


def _label(value):
    if not value:
        return None
    text = value.replace("<br>", " · ").replace("&nbsp;", " ")
    return " ".join(text.split()) or None


class Topology:
    """Immutable view of one bound Workflow Definition Revision."""

    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges
        self._outgoing = {node_id: [] for node_id in nodes}
        for edge in edges.values():
            self._outgoing[edge["source"]].append(edge["id"])
        for node_id in self._outgoing:
            self._outgoing[node_id].sort()

    def has_node(self, node_id):
        return node_id in self.nodes

    def node(self, node_id):
        try:
            return self.nodes[node_id]
        except KeyError:
            raise TopologyInvalid("node is not registered in the bound topology: " + str(node_id)) from None

    def semantic_type(self, node_id):
        return self.node(node_id)["semanticType"]

    def label(self, node_id):
        return self.node(node_id)["label"]

    def edge(self, edge_id):
        try:
            return self.edges[edge_id]
        except KeyError:
            raise TopologyInvalid("edge is not registered in the bound topology: " + str(edge_id)) from None

    def outgoing(self, node_id):
        return [self.edges[e] for e in self._outgoing[self.node(node_id)["id"]]]

    def counts(self):
        return dict(nodes=len(self.nodes), edges=len(self.edges))


def parse(raw):
    """Parse topology bytes into a Topology; any structural inconsistency raises TopologyInvalid."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise TopologyInvalid("topology is not well-formed XML: " + str(exc)) from exc
    cells = list(root.iter("mxCell"))
    by_cell, nodes = {}, {}
    for cell in cells:
        node_id = cell.get("topologyNodeId")
        if not node_id:
            continue
        if node_id in nodes:
            raise TopologyInvalid("duplicate topologyNodeId: " + node_id)
        semantic = cell.get("semanticType")
        if semantic not in SEMANTIC_TYPES:
            raise TopologyInvalid(f"node {node_id} carries an unknown semanticType: {semantic}")
        nodes[node_id] = dict(id=node_id, semanticType=semantic, label=_label(cell.get("value")) or node_id)
        by_cell[cell.get("id")] = node_id
    if not nodes:
        raise TopologyInvalid("topology registers no node")
    labels = {}
    for cell in cells:
        parent, value = cell.get("parent"), cell.get("value")
        if value and parent and cell.get("topologyNodeId") is None and cell.get("topologyEdgeId") is None:
            labels.setdefault(parent, _label(value))
    edges = {}
    for cell in cells:
        edge_id = cell.get("topologyEdgeId")
        if not edge_id:
            continue
        if edge_id in edges:
            raise TopologyInvalid("duplicate topologyEdgeId: " + edge_id)
        source, target = by_cell.get(cell.get("source")), by_cell.get(cell.get("target"))
        if source is None or target is None:
            raise TopologyInvalid(f"edge {edge_id} does not connect two registered nodes")
        edges[edge_id] = dict(id=edge_id, source=source, target=target, label=labels.get(cell.get("id")))
    if not edges:
        raise TopologyInvalid("topology registers no edge")
    topology = Topology(nodes, edges)
    if not topology.has_node(PUBLISH_NODE):
        raise TopologyInvalid("topology does not register the Publish node " + PUBLISH_NODE)
    missing = [e["id"] for node in nodes for e in topology.outgoing(node)
               if nodes[node]["semanticType"] == "HUMAN_GATE" and e["id"] not in SPEC_FR26_DECISION]
    if missing:
        raise TopologyInvalid("Human Gate edges without a spec FR-26 decision name: " + ", ".join(sorted(missing)))
    return topology


def decision_set(topology, node_id):
    """Legal Human decisions at a position, derived from its outgoing edges (spec FR-26).

    Returns [] for every node that is not a Human Gate: authority to decide is carried by the
    topology position, never by a caller-supplied list or by an interface element (NFR-04).
    """
    if topology.semantic_type(node_id) != "HUMAN_GATE":
        return []
    decisions = []
    for edge in topology.outgoing(node_id):
        target = topology.node(edge["target"])
        decisions.append(dict(edgeId=edge["id"], decision=SPEC_FR26_DECISION[edge["id"]],
                              label=edge["label"] or target["label"], target=target["id"],
                              targetSemanticType=target["semanticType"]))
    return decisions
