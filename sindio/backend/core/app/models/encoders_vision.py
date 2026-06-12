"""
Swin Transformer encoder for Sentinel-2 satellite patches.
Accepts 10-band (B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12) input.
Pretrained on Satellite-Pretrain (SSL on Sentinel-2 L1C).

Produces patch-level embeddings: (B, N_patches, 768).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple


class PatchMerging(nn.Module):
    """Downsample the spatial resolution by 2:1 and double the channel dim."""

    def __init__(self, dim: int, norm_layer: nn.Module = nn.LayerNorm):
        super().__init__()
        self.dim = dim
        self.reduction = nn.Linear(4 * dim, 2 * dim, bias=False)
        self.norm = norm_layer(4 * dim)

    def forward(self, x: torch.Tensor, h: int, w: int) -> Tuple[torch.Tensor, int, int]:
        B, L, C = x.shape
        x = x.view(B, h, w, C)
        x0 = x[:, 0::2, 0::2, :]
        x1 = x[:, 1::2, 0::2, :]
        x2 = x[:, 0::2, 1::2, :]
        x3 = x[:, 1::2, 1::2, :]
        x = torch.cat([x0, x1, x2, x3], dim=-1)
        x = x.view(B, -1, 4 * C)
        x = self.norm(x)
        x = self.reduction(x)
        return x, h // 2, w // 2


class WindowAttention(nn.Module):
    """Multi-head self-attention within shifted windows (Swin block)."""

    def __init__(self, dim: int, window_size: int, num_heads: int, qkv_bias: bool = True, attn_drop: float = 0.0, proj_drop: float = 0.0):
        super().__init__()
        self.dim = dim
        self.window_size = window_size
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = head_dim ** -0.5

        self.relative_position_bias_table = nn.Parameter(
            torch.zeros((2 * window_size - 1) * (2 * window_size - 1), num_heads)
        )
        coords_h = torch.arange(window_size)
        coords_w = torch.arange(window_size)
        coords = torch.stack(torch.meshgrid(coords_h, coords_w, indexing="ij"))
        coords_flatten = coords.reshape(2, -1)
        relative_coords = coords_flatten[:, :, None] - coords_flatten[:, None, :]
        relative_coords = relative_coords.permute(1, 2, 0).contiguous()
        relative_coords[:, :, 0] += window_size - 1
        relative_coords[:, :, 1] += window_size - 1
        relative_coords[:, :, 0] *= 2 * window_size - 1
        self.relative_position_index = relative_coords.sum(-1)

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.attn_drop = nn.Dropout(attn_drop)
        self.proj = nn.Linear(dim, dim)
        self.proj_drop = nn.Dropout(proj_drop)
        nn.init.trunc_normal_(self.relative_position_bias_table, std=0.02)

    def forward(self, x: torch.Tensor, mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q = q * self.scale
        attn = q @ k.transpose(-2, -1)
        rel_bias = self.relative_position_bias_table[self.relative_position_index.view(-1)].view(
            self.window_size * self.window_size, self.window_size * self.window_size, -1
        )
        rel_bias = rel_bias.permute(2, 0, 1).unsqueeze(0)
        attn = attn + rel_bias
        if mask is not None:
            nW = mask.shape[0]
            attn = attn.view(B // nW, nW, self.num_heads, N, N) + mask.unsqueeze(1).unsqueeze(0)
            attn = attn.view(-1, self.num_heads, N, N)
        attn = F.softmax(attn, dim=-1)
        attn = self.attn_drop(attn)
        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        x = self.proj_drop(x)
        return x


class SwinBlock(nn.Module):
    def __init__(self, dim: int, num_heads: int, window_size: int = 7, shift_size: int = 0, mlp_ratio: float = 4.0, drop: float = 0.0, attn_drop: float = 0.0):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        self.window_size = window_size
        self.shift_size = shift_size

        self.norm1 = nn.LayerNorm(dim)
        self.attn = WindowAttention(dim, window_size, num_heads, attn_drop=attn_drop, proj_drop=drop)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = nn.Sequential(
            nn.Linear(dim, int(dim * mlp_ratio)),
            nn.GELU(),
            nn.Dropout(drop),
            nn.Linear(int(dim * mlp_ratio), dim),
            nn.Dropout(drop),
        )

    def forward(self, x: torch.Tensor, h: int, w: int) -> Tuple[torch.Tensor, int, int]:
        shortcut = x
        x = self.norm1(x)
        x = x.view(-1, h, w, self.dim)
        if self.shift_size > 0:
            x = torch.roll(x, shifts=(-self.shift_size, -self.shift_size), dims=(1, 2))
        x, mask = self._window_partition(x)
        x = self.attn(x, mask)
        x = self._window_reverse(x, h, w)
        if self.shift_size > 0:
            x = torch.roll(x, shifts=(self.shift_size, self.shift_size), dims=(1, 2))
        x = x.view(-1, h * w, self.dim)
        x = shortcut + x
        x = x + self.mlp(self.norm2(x))
        return x, h, w

    def _window_partition(self, x: torch.Tensor) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        B, H, W, C = x.shape
        ws = self.window_size
        x = x.view(B, H // ws, ws, W // ws, ws, C)
        x = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, ws * ws, C)
        return x, None

    def _window_reverse(self, windows: torch.Tensor, H: int, W: int) -> torch.Tensor:
        ws = self.window_size
        B = int(windows.shape[0] / (H * W / ws / ws))
        x = windows.view(B, H // ws, W // ws, ws, ws, -1)
        x = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(B, H, W, -1)
        return x


class SwinEncoder(nn.Module):
    """Swin Transformer encoder for 10-band Sentinel-2 patches.

    Architecture follows Swin-T with modifications:
      - Input: 10 bands → patch embed projects to 96 dim
      - Stage 1: 96 dim → 192 dim (2 blocks)
      - Stage 2: 192 dim → 384 dim (2 blocks)
      - Stage 3: 384 dim → 768 dim (6 blocks)
      - Output: CLS token projection to 1024 dim
    """

    def __init__(
        self,
        in_channels: int = 10,
        image_size: int = 224,
        patch_size: int = 4,
        embed_dim: int = 96,
        depths: Tuple[int, ...] = (2, 2, 6, 2),
        num_heads: Tuple[int, ...] = (3, 6, 12, 24),
        window_size: int = 7,
        mlp_ratio: float = 4.0,
        drop_rate: float = 0.0,
        attn_drop_rate: float = 0.0,
        latent_dim: int = 1024,
    ):
        super().__init__()
        self.in_channels = in_channels
        self.patch_size = patch_size
        self.image_size = image_size
        self.num_patches = (image_size // patch_size) ** 2

        # Patch embedding — projects 10-band → embed_dim
        self.patch_embed = nn.Conv2d(
            in_channels, embed_dim, kernel_size=patch_size, stride=patch_size
        )

        # Learned positional encoding + CLS token
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))
        self.pos_embed = nn.Parameter(
            torch.zeros(1, self.num_patches + 1, embed_dim)
        )
        self.pos_drop = nn.Dropout(drop_rate)

        # Adapt first conv if pretrained weights from 3-band RGB exist
        self.band_adapter: Optional[nn.Conv2d] = None

        # Swin stages
        h = w = image_size // patch_size
        self.stages = nn.ModuleList()
        for i, (depth, n_heads) in enumerate(zip(depths, num_heads)):
            stage_blocks = nn.ModuleList()
            stage_dim = embed_dim * (2 ** i)
            if i > 0:
                merge = PatchMerging(embed_dim * (2 ** (i - 1)))
                self.stages[-1].append(merge)  # type: ignore
            for j in range(depth):
                shift = 0 if j % 2 == 0 else window_size // 2
                stage_blocks.append(
                    SwinBlock(
                        dim=stage_dim,
                        num_heads=n_heads,
                        window_size=window_size,
                        shift_size=shift,
                        mlp_ratio=mlp_ratio,
                        drop=drop_rate,
                        attn_drop=attn_drop_rate,
                    )
                )
            self.stages.append(stage_blocks)

        self.norm = nn.LayerNorm(embed_dim * (2 ** (len(depths) - 1)))
        self.latent_proj = nn.Linear(
            embed_dim * (2 ** (len(depths) - 1)), latent_dim
        )

        self._init_weights()

    def _init_weights(self):
        nn.init.trunc_normal_(self.pos_embed, std=0.02)
        nn.init.trunc_normal_(self.cls_token, std=0.02)
        nn.init.kaiming_normal_(self.patch_embed.weight, mode="fan_out")
        for n, m in self.named_modules():
            if isinstance(m, nn.LayerNorm):
                nn.init.constant_(m.bias, 0)
                nn.init.constant_(m.weight, 1.0)

    def init_band_adapter(self):
        """Create a small adapter if 3-band RGB pretrained weights are loaded."""
        self.band_adapter = nn.Conv2d(self.in_channels, 3, kernel_size=1, bias=False)
        nn.init.normal_(self.band_adapter.weight, std=0.01)

    def load_satellite_pretrain(self, checkpoint_path: str):
        """Load SSL-pretrained weights from Satellite-Pretrain."""
        state = torch.load(checkpoint_path, map_location="cpu")
        model_state = state.get("state_dict", state.get("model", state))
        missing, unexpected = self.load_state_dict(model_state, strict=False)
        logger = __import__("logging").getLogger(__name__)
        if missing:
            logger.warning("SwinEncoder: missing keys from pretrain — %s", missing[:5])
        if unexpected:
            logger.warning("SwinEncoder: unexpected keys — %s", unexpected[:5])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: (B, 10, 224, 224) Sentinel-2 patches.
        Returns:
            (B, 1024) latent patch embeddings.
        """
        B = x.shape[0]

        if self.band_adapter is not None:
            x_rgb = self.band_adapter(x)
            x = torch.cat([x_rgb, x[:, 3:]], dim=1)

        x = self.patch_embed(x)  # (B, embed_dim, H/p, W/p)
        x = x.flatten(2).transpose(1, 2)  # (B, N_patches, embed_dim)

        cls_tokens = self.cls_token.expand(B, -1, -1)
        x = torch.cat([cls_tokens, x], dim=1)
        x = x + self.pos_embed
        x = self.pos_drop(x)

        h = w = self.image_size // self.patch_size
        x = x[:, 1:, :]  # Remove CLS for spatial ops; re-add later

        for stage in self.stages:
            for blk in stage:
                if isinstance(blk, PatchMerging):
                    x, h, w = blk(x, h, w)
                else:
                    x, h, w = blk(x, h, w)

        x = self.norm(x)  # (B, N_patches_tiny, embed_dim_max)

        # Global average pooling + project to latent
        x = x.mean(dim=1)  # (B, embed_dim_max)
        x = self.latent_proj(x)  # (B, latent_dim)

        return x


def swin_tiny_10band(latent_dim: int = 1024, pretrained_path: Optional[str] = None) -> SwinEncoder:
    """Factory: Swin-T encoder adapted for 10-band Sentinel-2."""
    model = SwinEncoder(
        in_channels=10,
        image_size=224,
        patch_size=4,
        embed_dim=96,
        depths=(2, 2, 6, 2),
        num_heads=(3, 6, 12, 24),
        latent_dim=latent_dim,
    )
    if pretrained_path is not None:
        model.load_satellite_pretrain(pretrained_path)
    return model
