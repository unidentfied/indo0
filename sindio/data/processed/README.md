# Processed Data (Parquet)

Pipeline output in columnar format for fast ML training and analysis.

```
processed/
├── nodes_with_features.parquet   # Enriched infrastructure nodes
├── telemetry_hourly.parquet      # Aggregated sensor telemetry
├── alerts_labeled.parquet        # Labeled alerts for classification
├── simulations_outcomes.parquet  # Historical simulation results
└── gis_features.parquet          # Extracted GIS features for ML
```

All files in this directory are git-ignored.
