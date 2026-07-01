export interface FaqItem {
  q: string
  a: string
}

export const faqItems: FaqItem[] = [
  {
    q: 'What infrastructure types does Sindio monitor?',
    a: 'Sindio supports eight infrastructure types through a single unified registry: power grids, water networks, road systems, solid waste collection, pedestrian sidewalks, light rail transit (LRT), standard gauge railway (SGR), and airport operations. Each type uses the same parameterized monitoring pipeline with configurable thresholds, physics engines, and data sources.',
  },
  {
    q: 'How does stress classification work?',
    a: 'Sindio employs long-window classification combining STL seasonal decomposition and rolling Spearman rank correlation across up to 18 months of TimescaleDB hypertable data. Assets are classified as recurring-only, density-driven, mixed, or unstable — enabling targeted intervention strategies.',
  },
  {
    q: 'What happens when a data source becomes unavailable?',
    a: 'Every component includes graceful degradation. If PostGIS, Kafka, or an external API is unreachable, the system falls back to configurable synthetic data while tracking the mock-data ratio via Prometheus metrics. An alert triggers when fallback exceeds 10% for more than one hour.',
  },
  {
    q: 'Is Sindio suitable for cities other than Nairobi?',
    a: 'The unified registry and parameterized infrastructure monitor are designed for any dense urban environment. The current deployment is calibrated for Nairobi with local GIS boundaries, WorldPop raster data, and region-specific planning documents — the core engine is location-agnostic.',
  },
  {
    q: 'What physics engines are integrated?',
    a: 'Power grid simulations use pandapower. Water networks use EPANET hydraulic models. Road networks use a modified cell-transmission model. Infrastructure types without dedicated physics engines use configurable heuristic stress calculations.',
  },
  {
    q: 'How often is the stress data updated?',
    a: 'Update intervals are configurable per infrastructure type through the centralized registry. Real-time data streams via Kafka feed into TimescaleDB hypertables, while batch processing handles historical trend analysis. The platform supports intervals as low as 15 seconds for critical infrastructure.',
  },
  {
    q: 'What data privacy measures does Sindio implement?',
    a: 'All geospatial data is anonymized at the grid-cell level. Individual asset coordinates are aggregated into hexagonal bins before any public-facing visualization. The platform complies with the Kenyan Data Protection Act and aligns with GDPR principles for any cross-border data handling.',
  },
  {
    q: 'Can I integrate Sindio with my existing monitoring tools?',
    a: 'Yes. Sindio exposes Prometheus-compatible metrics at /metrics on every service, supports WebSocket streaming for real-time updates, provides a REST API for programmatic access, and ships with pre-built Grafana dashboards for integration into existing observability stacks.',
  },
]
