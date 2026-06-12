# Raw GIS & Utility Data

Place raw source files here before processing:

```
raw/
├── nairobi_boundary.geojson      # Administrative boundaries
├── power_grid_nodes.shp          # Power substations & lines
├── water_network.gpkg            # Pipes, pumps, reservoirs
├── road_network.geojson          # Road segments & intersections
├── population_density.tif        # WorldPop / census raster
├── transit_routes.gpkg           # Bus rapid transit and rail
├── flood_zones.geojson           # Flood risk zones
└── utility_consumption.csv       # Historic consumption data
```

All files in this directory are git-ignored.
Use `dvc add data/raw/` to track with DVC if needed.
