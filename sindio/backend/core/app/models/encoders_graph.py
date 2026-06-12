"""
Graph Isomorphism Network (GIN) encoder for infrastructure topology.

Nodes  = infrastructure assets (substations, pump stations, intersections).
Edges  = connectivity (transmission lines, pipes, road segments).
Input  = node features (capacity, load, age, type embedding) + adjacency.
Output = (B, 1024) graph-level embedding.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, List


class GINConv(nn.Module):
    """Graph Isomorphism Network convolution.

    h_i' = MLP((1 + eps) * h_i + sum_{j in N(i)} h_j)
    """

    def __init__(self, dim: int, eps: float = 0.0, train_eps: bool = True):
        super().__init__()
        if train_eps:
            self.eps = nn.Parameter(torch.tensor(eps))
        else:
            self.register_buffer("eps", torch.tensor(eps))
        self.mlp = nn.Sequential(
            nn.Linear(dim, dim * 2),
            nn.BatchNorm1d(dim * 2),
            nn.ReLU(),
            nn.Linear(dim * 2, dim),
        )

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        row, col = edge_index
        out = x.clone()
        out.index_add_(0, row, x[col])
        out.mul_(1.0 + self.eps)
        out = self.mlp(out)
        return out


class EdgeGating(nn.Module):
    """Learn a scalar weight per edge based on edge features."""

    def __init__(self, edge_dim: int, out_dim: int = 1):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(edge_dim, edge_dim),
            nn.ReLU(),
            nn.Linear(edge_dim, out_dim),
        )

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        edge_attr: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        if edge_attr is None:
            return x[edge_index[1]]

        gate = self.net(edge_attr).sigmoid()  # (E, 1)
        aggr = x[edge_index[1]] * gate
        return aggr


class GINEncoder(nn.Module):
    """GIN encoder for infrastructure graph.

    Input:
      - node_features: (N, node_dim) per graph
      - edge_index: (2, E)
      - edge_attr: (E, edge_dim) optional
      - batch: (N,) batch assignment for multi-graph batches

    Architecture:
      - Node type embedding → concat with continuous features
      - 4 × GINConv (128 → 256 → 512 → 768)
      - Readout: mean + max → 1536 → 1024
    """

    def __init__(
        self,
        node_feat_dim: int = 16,
        node_type_count: int = 5,
        type_embed_dim: int = 32,
        edge_feat_dim: int = 6,
        hidden_dims: List[int] = [128, 256, 512, 768],
        latent_dim: int = 1024,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.type_embed = nn.Embedding(node_type_count, type_embed_dim)

        input_dim = node_feat_dim + type_embed_dim
        self.input_proj = nn.Linear(input_dim, hidden_dims[0])

        self.convs = nn.ModuleList()
        self.norms = nn.ModuleList()
        for i in range(len(hidden_dims)):
            self.convs.append(GINConv(hidden_dims[i]))
            self.norms.append(nn.BatchNorm1d(hidden_dims[i]))

        self.edge_gates = nn.ModuleList([
            EdgeGating(edge_feat_dim) for _ in range(len(hidden_dims))
        ])
        self.dropout = nn.Dropout(dropout)

        # Readout: concat mean + max across layers → MLP → latent
        total_readout = sum(hidden_dims) * 2
        self.readout_net = nn.Sequential(
            nn.Linear(total_readout, hidden_dims[-1]),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dims[-1], latent_dim),
        )

    def forward(
        self,
        node_features: torch.Tensor,
        edge_index: torch.Tensor,
        node_types: Optional[torch.Tensor] = None,
        edge_attr: Optional[torch.Tensor] = None,
        batch: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        Args:
            node_features: (N, node_feat_dim)
            edge_index: (2, E)
            node_types: (N,) int tensor of node type IDs
            edge_attr: (E, edge_feat_dim)
            batch: (N,) batch assignment indices
        Returns:
            (B, 1024) graph-level embeddings.
        """
        N = node_features.shape[0]

        if node_types is not None:
            type_emb = self.type_embed(node_types)  # (N, type_embed_dim)
            x = torch.cat([node_features, type_emb], dim=-1)
        else:
            x = F.pad(node_features, (0, self.type_embed.embedding_dim))

        x = self.input_proj(x)

        layer_outputs: List[torch.Tensor] = []

        for conv, norm, gate in zip(self.convs, self.norms, self.edge_gates):
            aggr = gate(x, edge_index, edge_attr)
            x = x + aggr
            x = conv(x, edge_index)
            x = norm(x)
            x = F.relu(x)
            x = self.dropout(x)
            layer_outputs.append(x)

        # Readout per graph in the batch
        if batch is None:
            batch = torch.zeros(N, dtype=torch.long, device=x.device)

        graph_embeds: List[torch.Tensor] = []
        for y in layer_outputs:
            mean_pool = self._scatter_mean(y, batch)
            max_pool = self._scatter_max(y, batch)
            graph_embeds.extend([mean_pool, max_pool])

        global_x = torch.cat(graph_embeds, dim=-1)  # (B, total_readout)
        out = self.readout_net(global_x)  # (B, latent_dim)
        return out

    @staticmethod
    def _scatter_mean(x: torch.Tensor, batch: torch.Tensor) -> torch.Tensor:
        num_graphs = batch.max().item() + 1
        out = torch.zeros(num_graphs, x.size(1), device=x.device, dtype=x.dtype)
        count = torch.zeros(num_graphs, device=x.device, dtype=x.dtype)
        out.index_add_(0, batch, x)
        count.index_add_(0, batch, torch.ones(x.size(0), device=x.device))
        return out / count.clamp(min=1).unsqueeze(1)

    @staticmethod
    def _scatter_max(x: torch.Tensor, batch: torch.Tensor) -> torch.Tensor:
        num_graphs = batch.max().item() + 1
        out = torch.full(
            (num_graphs, x.size(1)), float("-inf"), device=x.device, dtype=x.dtype
        )
        out.index_put_(
            (batch.unsqueeze(-1).expand(-1, x.size(1)),
             torch.arange(x.size(1), device=x.device).unsqueeze(0).expand(batch.size(0), -1)),
            x,
            accumulate=True,
        )
        return out.amax(dim=0).unsqueeze(0) if num_graphs == 1 else out
