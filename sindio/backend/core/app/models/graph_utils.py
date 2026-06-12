"""
Encode raw node + edge features into the format expected by GINEncoder.

Converts infrastructure_assets rows (from PostGIS) into PyG-style
batch graphs with node features, edge index, edge attributes, and
a batch-assignment tensor.

Each infrastructure type (power/water/road) forms a subgraph;
edges exist where assets share a voltage zone, pressure zone, or road corridor.
"""

import torch
import numpy as np
from typing import Dict, List, Optional, Tuple


def build_batch_graph(
    nodes: List[Dict],
    edges: List[Dict],
    node_feat_cols: List[str],
    edge_feat_cols: List[str],
    node_type_col: str = "asset_type",
    device: torch.device = torch.device("cpu"),
) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    """Build a batched PyG-style graph from dicts of node/edge data.

    Args:
        nodes: list of dicts with keys: id, asset_type, + feature columns.
        edges: list of dicts with keys: source_node_id, target_node_id, + feature columns.
        node_feat_cols: column names to use as node features.
        edge_feat_cols: column names to use as edge features.
        node_type_col: column to use as categorical node type.
        device: target device.

    Returns:
        node_features:  (N, len(node_feat_cols))
        edge_index:     (2, E)
        edge_attr:      (E, len(edge_feat_cols))
        node_types:     (N,) int tensor
        batch:          (N,) all-zero tensor (single graph)

    Edge-case: an empty nodes dict produces empty tensors with the right shape.
    """
    if not nodes:
        return (
            torch.empty(0, len(node_feat_cols), device=device),
            torch.empty(2, 0, dtype=torch.long, device=device),
            torch.empty(0, len(edge_feat_cols), device=device),
            torch.empty(0, dtype=torch.long, device=device),
            torch.empty(0, dtype=torch.long, device=device),
        )

    # Node ID → integer index
    id_to_idx = {n["id"]: i for i, n in enumerate(nodes)}

    type_map: Dict[str, int] = {
        t: i for i, t in enumerate(sorted(set(n.get(node_type_col, "unknown") for n in nodes)))
    }

    node_feat = torch.tensor(
        [[float(n.get(c, 0.0)) for c in node_feat_cols] for n in nodes],
        dtype=torch.float32,
        device=device,
    )
    node_types = torch.tensor(
        [type_map.get(n.get(node_type_col, "unknown"), 0) for n in nodes],
        dtype=torch.long,
        device=device,
    )

    # Build edge index & attributes
    src, tgt = [], []
    edge_attrs = []
    for e in edges:
        sid = e.get("source_node_id", e.get("source"))
        tid = e.get("target_node_id", e.get("target"))
        if sid in id_to_idx and tid in id_to_idx:
            src.append(id_to_idx[sid])
            tgt.append(id_to_idx[tid])
            edge_attrs.append([float(e.get(c, 0.0)) for c in edge_feat_cols])
            # Add reverse edge for undirected graph
            src.append(id_to_idx[tid])
            tgt.append(id_to_idx[sid])
            edge_attrs.append([float(e.get(c, 0.0)) for c in edge_feat_cols])

    if src:
        edge_index = torch.tensor([src, tgt], dtype=torch.long, device=device)
        edge_attr = torch.tensor(edge_attrs, dtype=torch.float32, device=device)
    else:
        edge_index = torch.empty(2, 0, dtype=torch.long, device=device)
        edge_attr = torch.empty(0, len(edge_feat_cols), device=device)

    batch = torch.zeros(len(nodes), dtype=torch.long, device=device)

    return node_feat, edge_index, edge_attr, node_types, batch
