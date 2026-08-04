def __getattr__(name: str):
    if name == "SindioFoundation":
        from .sindio_foundation import SindioFoundation as _cls
        return _cls
    if name == "SwinEncoder":
        from app.models.encoders_vision import SwinEncoder as _cls
        return _cls
    if name == "GINEncoder":
        from app.models.encoders_graph import GINEncoder as _cls
        return _cls
    if name == "TemporalTransformerEncoder":
        from app.models.encoders_temporal import TemporalTransformerEncoder as _cls
        return _cls
    if name == "CrossModalFusion":
        from app.models.fusion import CrossModalFusion as _cls
        return _cls
    if name == "StressHead":
        from app.models.heads import StressHead as _cls
        return _cls
    if name == "ForecastHead":
        from app.models.heads import ForecastHead as _cls
        return _cls
    if name == "BreachClassifier":
        from app.models.heads import BreachClassifier as _cls
        return _cls
    if name == "SindioLoss":
        from app.models.losses import SindioLoss as _cls
        return _cls
    if name == "build_batch_graph":
        from app.models.graph_utils import build_batch_graph as _fn
        return _fn
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "SindioFoundation",
    "SwinEncoder",
    "GINEncoder",
    "TemporalTransformerEncoder",
    "CrossModalFusion",
    "StressHead",
    "ForecastHead",
    "BreachClassifier",
    "SindioLoss",
    "build_batch_graph",
]
