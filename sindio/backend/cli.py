import typer
import os
import uvicorn

from backend.core.app.logging import logger
from backend.app.main import app as api_app
from backend.core.app.services.ingest_geospatial import run as ingest_all

app = typer.Typer(help="Sindio CLI for managing services")

@app.command()
def serve(host: str = "0.0.0.0", port: int = 8081, reload: bool = True):
    """Run the Sindio mock API server using uvicorn."""
    logger.info("Starting Sindio mock API server", host=host, port=port)
    uvicorn.run(api_app, host=host, port=port, reload=reload)

@app.command()
def ingest(
    parallel: bool = typer.Option(False, "-p", "--parallel", help="Run asset ingestion in parallel."),
):
    """Execute the full data ingestion pipeline.

    The ``parallel`` flag overrides the ``parallel`` entry in ``features.yaml``.
    """
    logger.info("Starting data ingestion pipeline", parallel=parallel)
    # Override feature flag for this run
    from backend.core.app.services.ingest_geospatial import _load_feature_flags, run
    flags = _load_feature_flags()
    flags["parallel"] = parallel
    results = run(parallel=parallel, feature_flags=flags) if hasattr(run, "feature_flags") else run(parallel=parallel)
    logger.info("Ingestion completed", results=results)

if __name__ == "__main__":
    app()
