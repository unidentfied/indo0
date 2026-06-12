"""
RAG-based What-If Scenario Generator for Sindio.

Pipeline:
  1. Embed user query → search Qdrant for similar cached scenarios
  2. If fresh cache hit → return cached parameters directly
  3. If cache miss:
     a. Retriever 1: historical growth patterns (similar wards / % growth)
     b. Retriever 2: mitigation strategies (Nairobi planning docs)
     c. Feed context + query → GPT-4o → structured JSON parameters
  4. Validate output → cache in Qdrant → return

Output is a parameter dict consumable by SimulationEngine.run().
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("sindio.scenario")


COLLECTION_SCENARIOS = os.getenv(
    "QDRANT_COLLECTION_SCENARIOS", "sindio_scenarios"
)
COLLECTION_PLANNING = os.getenv(
    "QDRANT_COLLECTION_PLANNING", "sindio_planning_docs"
)
SCENARIO_VECTOR_DIM = 384        # MiniLM-L6-v2
CACHE_FRESHNESS_DAYS = 7         # scenario reuse window
SIMILARITY_THRESHOLD = 0.85
RETRIEVAL_TOP_K = 5


# ──────────────────────────────────────────────────────────────
# Embedding helper
# ──────────────────────────────────────────────────────────────


def _get_embedder():
    """Lazy-load sentence-transformers for query embedding."""
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")
    except ImportError:
        logger.warning(
            "sentence-transformers not installed. "
            "Install with: pip install sentence-transformers"
        )
        return None


# ──────────────────────────────────────────────────────────────
# Scenario data structures
# ──────────────────────────────────────────────────────────────


@dataclass
class ScenarioPayload:
    """A generated 'what-if' scenario."""
    scenario_id: str
    query_text: str
    generated_at: str
    parameters: Dict[str, Any]  # passed to SimulationEngine.run()
    explanation: str
    historical_references: List[Dict[str, str]]
    mitigation_strategies: List[Dict[str, str]]
    source: str  # "cache_hit" | "llm_generated"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "query_text": self.query_text,
            "generated_at": self.generated_at,
            "parameters": self.parameters,
            "explanation": self.explanation,
            "historical_references": self.historical_references,
            "mitigation_strategies": self.mitigation_strategies,
            "source": self.source,
        }


# ──────────────────────────────────────────────────────────────
# Planning document templates (in production: loaded from docs)
# ──────────────────────────────────────────────────────────────


NAIROBI_PLANNING_CHUNKS: List[Dict[str, str]] = [
    {
        "title": "Nairobi Integrated Urban Development Master Plan 2014-2030",
        "section": "Infrastructure Expansion",
        "text": (
            "Water supply expansion to Eastlands: KES 12B allocated for Northern Collector Tunnel Phase II. "
            "Power: 4 new 66kV substations in Dandora, Kayole, Embakasi corridors. "
            "Transport: BRT Line 3 (Dandora–CBD) and Line 4 (Eastlands Loop) with dedicated lanes."
        ),
        "ward": "Eastlands",
        "year": 2024,
    },
    {
        "title": "Nairobi City County Annual Development Plan 2025/2026",
        "section": "Budget Allocation",
        "text": (
            "KES 50M allocated for informal settlement upgrading in Mathare and Kibera. "
            "KES 30M for water kiosks and boreholes in Eastlands. "
            "KES 80M for road rehabilitation: Outer Ring Road, Jogoo Road, Kangundo Road. "
            "KES 15M for street lighting in high-density residential areas."
        ),
        "ward": "Eastlands",
        "year": 2025,
    },
    {
        "title": "Nairobi Metro 2030 Strategy",
        "section": "Densification Policy",
        "text": (
            "Target density: 300 persons/ha in transit corridors. "
            "Densification priority zones: Eastlands (Kayole, Dandora, Umoja), "
            "with minimum plot ratio of 150% in new developments. "
            "Infrastructure trigger: when ward density exceeds 250 persons/ha, "
            "mandatory impact assessment required."
        ),
        "ward": "Eastlands",
        "year": 2023,
    },
    {
        "title": "Westlands Development Framework 2022",
        "section": "Lessons Learned",
        "text": (
            "Westlands experienced 14% population growth in 2022 driven by commercial rezoning. "
            "Resulting water deficit of 8,200 m³/day was partially mitigated by emergency boreholes (KES 25M). "
            "Power load increased 18% — 2 new 33kV feeders installed at KES 40M. "
            "Traffic congestion rose 22% — BRT feeder routes adjusted. "
            "Key lesson: proactive infrastructure scaling 6 months ahead of zoning changes."
        ),
        "ward": "Westlands",
        "year": 2022,
    },
    {
        "title": "Nairobi Climate Action Plan 2023-2027",
        "section": "Resilient Infrastructure",
        "text": (
            "Flood mitigation: stormwater drainage along Ngong River and Mathare River (KES 200M). "
            "Green corridors: riparian buffers 30m minimum, enforcement by 2026. "
            "Heat island reduction: mandatory green roofing for new commercial builds > 500 m²."
        ),
        "ward": "City-wide",
        "year": 2023,
    },
    {
        "title": "Kenya Power Distribution Master Plan 2020-2040",
        "section": "Nairobi Region",
        "text": (
            "Nairobi peak demand forecast: 1,200 MW by 2030 (from 680 MW in 2020). "
            "Substation upgrades scheduled: Dandora (132kV), Embakasi (220kV). "
            "Transformer replacement program: 15-year lifecycle, prioritise areas > 85% load factor."
        ),
        "ward": "City-wide",
        "year": 2020,
    },
]


# ──────────────────────────────────────────────────────────────
# Scenario Generator
# ──────────────────────────────────────────────────────────────


class ScenarioGenerator:
    """RAG pipeline for 'what-if' urban planning scenarios.

    Usage:
        gen = ScenarioGenerator(openai_api_key="...")
        result = gen.generate("What if Eastlands population grows 15%?")
        # result.parameters → {"growth_rate": 0.15, "wards": ["Eastlands"], ...}
        # Pass to SimulationEngine.run(**result.parameters)
    """

    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        model_name: str = "gpt-4o",
        docs: Optional[List[Dict[str, str]]] = None,
    ):
        self.api_key = openai_api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model_name
        self.docs = docs or NAIROBI_PLANNING_CHUNKS

        # Lazy-loaded cache client
        self._cache_client: Any = None
        self._embedder: Any = None

    @property
    def cache(self):
        if self._cache_client is None:
            from app.services.qdrant_cache import QdrantCacheClient

            self._cache_client = QdrantCacheClient(collection=COLLECTION_SCENARIOS)
        return self._cache_client

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = _get_embedder()
        return self._embedder

    def generate(
        self,
        user_query: str,
        force_regenerate: bool = False,
        return_cache_only: bool = False,
    ) -> ScenarioPayload:
        """Generate a what-if scenario from a natural-language query.

        Args:
            user_query: e.g. "What if Eastlands population grows 15% next year?"
            force_regenerate: skip cache lookup, always call LLM.
            return_cache_only: if cache miss, return None instead of calling LLM.

        Returns:
            ScenarioPayload with parameters ready for SimulationEngine.
        """
        query_emb = self._embed_query(user_query)

        # ── Cache check ─────────────────────────────────
        if not force_regenerate:
            cached = self._check_scenario_cache(query_emb, user_query)
            if cached is not None:
                return cached

        if return_cache_only:
            logger.warning("Cache miss and return_cache_only=True — returning None.")
            raise ValueError("No cached scenario available for this query.")

        # ── Retrieval ────────────────────────────────────
        retrieval = self._retrieve_context(query_emb, user_query)

        # ── LLM synthesis ────────────────────────────────
        scenario = self._call_llm(
            user_query=user_query,
            historical_context=retrieval["historical"],
            planning_context=retrieval["planning"],
        )

        # ── Cache the result ─────────────────────────────
        self._cache_scenario(scenario, query_emb)

        return scenario

    # ── Embedding ───────────────────────────────────────────

    def _embed_query(self, text: str) -> np.ndarray:
        """Embed user query → (384,) vector."""
        if self.embedder is None:
            return np.random.randn(SCENARIO_VECTOR_DIM).astype(np.float32)

        return self.embedder.encode(text, normalize_embeddings=True).astype(np.float32)

    # ── Cache check ─────────────────────────────────────────

    def _check_scenario_cache(
        self, query_emb: np.ndarray, user_query: str
    ) -> Optional[ScenarioPayload]:
        """Check if a very similar scenario was already generated."""
        from qdrant_client.http.models import FieldCondition, Filter, Range

        freshness_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=CACHE_FRESHNESS_DAYS)
        ).isoformat()

        try:
            results = self.cache.client.search(
                collection_name=COLLECTION_SCENARIOS,
                query_vector=query_emb.tolist(),
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="generated_at",
                            range=Range(gte=freshness_cutoff),
                        ),
                    ]
                ),
                limit=1,
                score_threshold=SIMILARITY_THRESHOLD,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            self.cache.ensure_collection()
            return None

        if results:
            hit = results[0]
            payload = hit.payload or {}
            logger.info(
                "Scenario cache HIT (score=%.4f, id=%s)",
                hit.score,
                payload.get("scenario_id", "?"),
            )
            return ScenarioPayload(
                scenario_id=payload.get("scenario_id", ""),
                query_text=user_query,
                generated_at=payload.get("generated_at", ""),
                parameters=payload.get("parameters", {}),
                explanation=payload.get("explanation", ""),
                historical_references=payload.get("historical_references", []),
                mitigation_strategies=payload.get("mitigation_strategies", []),
                source="cache_hit",
            )
        return None

    # ── Retrieval ───────────────────────────────────────────

    def _retrieve_context(
        self, query_emb: np.ndarray, user_query: str
    ) -> Dict[str, str]:
        """Retrieve historical patterns and planning docs relevant to the query.

        Returns:
            {"historical": "...", "planning": "..."}
        """
        # Retriever 1: similar past scenarios from Qdrant
        historical = self._retrieve_historical_patterns(query_emb, user_query)

        # Retriever 2: relevant planning documents
        planning = self._retrieve_planning_docs(user_query)

        return {"historical": historical, "planning": planning}

    def _retrieve_historical_patterns(
        self, query_emb: np.ndarray, user_query: str
    ) -> str:
        """Search stored scenarios for similar growth patterns."""
        try:
            results = self.cache.client.search(
                collection_name=COLLECTION_SCENARIOS,
                query_vector=query_emb.tolist(),
                limit=RETRIEVAL_TOP_K,
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return "No historical scenarios found."

        if not results:
            return "No historical scenarios found."

        parts = []
        for hit in results:
            p = hit.payload or {}
            params = p.get("parameters", {})
            expl = p.get("explanation", "")
            parts.append(
                f"- Scenario '{p.get('query_text', '?')}' "
                f"({p.get('generated_at', '?')[:10]}): "
                f"growth={params.get('growth_rate', '?')}, "
                f"budget={params.get('mitigation_budget', '?')}. "
                f"Result: {expl[:200]}"
            )
        return "\n".join(parts)

    def _retrieve_planning_docs(self, user_query: str) -> str:
        """Keyword-search embedded planning documents for relevant sections."""
        query_lower = user_query.lower()
        matched = []

        # Simple keyword matching across doc chunks
        ward_keywords = self._extract_ward_keywords(user_query)
        topic_keywords = self._extract_topic_keywords(user_query)

        for doc in self.docs:
            score = 0
            text_lower = doc["text"].lower() + doc["title"].lower()

            if any(w in text_lower for w in ward_keywords):
                score += 3
            if any(w in text_lower for w in topic_keywords):
                score += 2
            if doc["ward"].lower() in query_lower:
                score += 2
            if any(kw in text_lower for kw in query_lower.split() if len(kw) > 3):
                score += 1

            if score >= 2:
                matched.append((score, doc))

        matched.sort(key=lambda x: -x[0])
        top = matched[:RETRIEVAL_TOP_K]

        if not top:
            return "No relevant planning documents found."

        parts = []
        for score, doc in top:
            parts.append(
                f"- {doc['title']} ({doc['year']}), {doc['section']} "
                f"[ward={doc['ward']}]: {doc['text']}"
            )
        return "\n".join(parts)

    # ── LLM Call ────────────────────────────────────────────

    def _call_llm(
        self,
        user_query: str,
        historical_context: str,
        planning_context: str,
    ) -> ScenarioPayload:
        """Call GPT-4o with RAG context to generate structured scenario parameters."""
        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(
            user_query, historical_context, planning_context
        )

        if not self.api_key or self.api_key.startswith("sk-placeholder"):
            logger.warning(
                "No valid OpenAI API key — returning deterministically simulated scenario."
            )
            return self._simulate_llm_response(user_query, historical_context, planning_context)

        try:
            import openai

            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            return self._parse_llm_response(raw, user_query, historical_context, planning_context)

        except Exception as exc:
            logger.error("LLM call failed: %s. Using simulated response.", exc)
            return self._simulate_llm_response(user_query, historical_context, planning_context)

    def _build_system_prompt(self) -> str:
        return (
            "You are an urban planning simulation engine for Nairobi, Kenya. "
            "You generate structured JSON parameters for predictive infrastructure "
            "stress tests. Your output MUST be valid JSON with exactly the following keys:\n\n"
            "{\n"
            '  "explanation": "<paragraph explaining the scenario and reasoning>",\n'
            '  "parameters": {\n'
            '    "wards": ["<ward1>", "<ward2>"],\n'
            '    "growth_rate": <float 0.0–0.5>,\n'
            '    "density_projection_years": <5|10|15>,\n'
            '    "mitigation_budget_kes": <integer>,\n'
            '    "infrastructure_focus": ["power"|"water"|"roads"],\n'
            '    "trigger_cascading_check": <boolean>,\n'
            '    "notes": "<additional context>"\n'
            "  },\n"
            '  "historical_references": [\n'
            '    {"ward": "<name>", "year": <int>, "growth_pct": <float>, "outcome": "<summary>"}\n'
            "  ],\n"
            '  "mitigation_strategies": [\n'
            '    {"title": "<name>", "source_year": <int>, "estimated_cost_kes": <int>, "description": "<text>"}\n'
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Use the provided historical context and planning documents.\n"
            "- Budgets must be realistic for Nairobi (KES 5M–500M range).\n"
            "- Wards should be real Nairobi wards from the context.\n"
            "- If no specific ward is mentioned, default to the ward in context.\n"
            "- Infrastructure focus should match the query (water if water mentioned, etc.).\n"
        )

    def _build_user_prompt(
        self,
        user_query: str,
        historical_context: str,
        planning_context: str,
    ) -> str:
        return (
            f"## User Query\n{user_query}\n\n"
            f"## Historical Similar Scenarios (past simulation patterns)\n{historical_context}\n\n"
            f"## Nairobi Planning Documents & Policies\n{planning_context}\n\n"
            "Generate a structured scenario JSON based on the query and context above."
        )

    def _parse_llm_response(
        self,
        raw: Optional[str],
        user_query: str,
        historical_context: str,
        planning_context: str,
    ) -> ScenarioPayload:
        """Parse LLM JSON output into a ScenarioPayload."""
        if raw is None:
            return self._simulate_llm_response(user_query, historical_context, planning_context)

        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON — using simulated response.")
            return self._simulate_llm_response(user_query, historical_context, planning_context)

        return ScenarioPayload(
            scenario_id=self._make_scenario_id(user_query),
            query_text=user_query,
            generated_at=datetime.now(timezone.utc).isoformat(),
            parameters=data.get("parameters", {}),
            explanation=data.get("explanation", ""),
            historical_references=data.get("historical_references", []),
            mitigation_strategies=data.get("mitigation_strategies", []),
            source="llm_generated",
        )

    def _simulate_llm_response(
        self,
        user_query: str,
        historical_context: str,
        planning_context: str,
    ) -> ScenarioPayload:
        """Deterministic fallback when LLM is unavailable.

        Extracts basic parameters from the user query via keyword matching.
        """
        growth = self._extract_growth_rate(user_query)
        wards = self._extract_ward_keywords(user_query) or ["Eastlands"]
        focus = self._extract_topic_keywords(user_query) or ["water", "power", "roads"]
        budget = self._extract_budget(user_query)

        params = {
            "wards": wards,
            "growth_rate": growth,
            "density_projection_years": 10,
            "mitigation_budget_kes": budget,
            "infrastructure_focus": focus,
            "trigger_cascading_check": True,
            "notes": f"Auto-generated from query: '{user_query}'. "
                     "Parameters extrapolated via keyword extraction.",
        }

        return ScenarioPayload(
            scenario_id=self._make_scenario_id(user_query),
            query_text=user_query,
            generated_at=datetime.now(timezone.utc).isoformat(),
            parameters=params,
            explanation=(
                f"Simulated scenario: {wards[0]} at {growth:.0%} growth over "
                f"{params['density_projection_years']} years. "
                f"Budget: KES {budget:,}. "
                f"Focusing on {', '.join(focus)} infrastructure. "
                f"Generated deterministically (LLM unavailable)."
            ),
            historical_references=[
                {
                    "ward": "Westlands",
                    "year": 2022,
                    "growth_pct": 14.0,
                    "outcome": (
                        "Water deficit 8,200 m³/day; mitigated with emergency "
                        "boreholes (KES 25M). Power +18%, traffic +22%."
                    ),
                }
            ],
            mitigation_strategies=[
                {
                    "title": "Proactive infrastructure scaling",
                    "source_year": 2022,
                    "estimated_cost_kes": budget,
                    "description": (
                        "Apply Westlands 2022 lessons: scale infrastructure "
                        "6 months ahead of zoning changes. Allocate to water, "
                        "power, and BRT adjustments."
                    ),
                }
            ],
            source="llm_generated",
        )

    # ── Caching ──────────────────────────────────────────────

    def _cache_scenario(self, scenario: ScenarioPayload, embedding: np.ndarray):
        """Store generated scenario in Qdrant for future reuse."""
        import uuid

        from qdrant_client.http.models import PointStruct

        try:
            self.cache.ensure_collection()
            point = PointStruct(
                id=scenario.scenario_id,
                vector=embedding.tolist(),
                payload={
                    "scenario_id": scenario.scenario_id,
                    "query_text": scenario.query_text,
                    "generated_at": scenario.generated_at,
                    "parameters": json.dumps(scenario.parameters),
                    "explanation": scenario.explanation,
                    "historical_references": json.dumps(scenario.historical_references),
                    "mitigation_strategies": json.dumps(scenario.mitigation_strategies),
                    "source": scenario.source,
                },
            )
            self.cache.client.upsert(
                collection_name=COLLECTION_SCENARIOS,
                points=[point],
            )
            logger.info("Cached scenario %s in Qdrant", scenario.scenario_id)
        except Exception as exc:
            logger.error("Failed to cache scenario: %s", exc)

    # ── Query parsing helpers ────────────────────────────────

    @staticmethod
    def _extract_ward_keywords(query: str) -> List[str]:
        KNOWN_WARDS = [
            "eastlands", "westlands", "kilimani", "kibera", "mathare",
            "kayole", "dandora", "umoja", "embakasi", "langata",
            "karen", "parklands", "kasarani", "central district",
            "huruma", "korogocho", "mukuru kwa njenga", "kangemi",
            "ruaraka", "roysambu", "kariobangi", "pangani", "ngara",
        ]
        q = query.lower()
        return [w.capitalize() for w in KNOWN_WARDS if w in q]

    @staticmethod
    def _extract_topic_keywords(query: str) -> List[str]:
        mapping = {
            "water": ["water", "sewage", "drainage", "borehole", "reservoir", "pipe"],
            "power": ["power", "electricity", "substation", "transformer", "load shedding"],
            "roads": ["road", "traffic", "congestion", "brt", "transit", "highway", "transport"],
        }
        q = query.lower()
        result = []
        for infra, kws in mapping.items():
            if any(kw in q for kw in kws):
                result.append(infra)
        return result if result else ["power", "water", "roads"]

    @staticmethod
    def _extract_growth_rate(query: str) -> float:
        """Extract percentage growth from query text."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", query)
        if match:
            return float(match.group(1)) / 100.0

        match = re.search(r"grows?\s*(\d+(?:\.\d+)?)", query, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            return val / 100.0 if val > 1 else val

        return 0.15

    @staticmethod
    def _extract_budget(query: str) -> int:
        """Extract budget in KES from query text."""
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:M|million|KES|KSh)", query, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if "M" in query or "million" in query.lower():
                val *= 1_000_000
            return int(val)
        return 50_000_000

    @staticmethod
    def _make_scenario_id(query: str) -> str:
        h = hashlib.sha256(query.encode()).hexdigest()[:12]
        return f"scenario_{h}"


# ──────────────────────────────────────────────────────────────
# Convenience: run a scenario directly against the simulation engine
# ──────────────────────────────────────────────────────────────


def run_what_if(
    user_query: str,
    openai_api_key: Optional[str] = None,
    force_regenerate: bool = False,
) -> Tuple[ScenarioPayload, Any]:
    """Full pipeline: generate scenario → run simulation → return both.

    Returns:
        (ScenarioPayload, GeoDataFrame from SimulationEngine)
    """
    gen = ScenarioGenerator(openai_api_key=openai_api_key)
    scenario = gen.generate(user_query, force_regenerate=force_regenerate)

    logger.info("Running simulation for scenario: %s", scenario.scenario_id)

    from app.services.simulation_engine import SimulationEngine
    from app.services.data_fusion import DataFusionEngine

    fusion = DataFusionEngine()
    ds = fusion.fuse()

    engine = SimulationEngine()
    gdf = engine.run(
        fused_dataset=ds,
        density_projection_years=scenario.parameters.get("density_projection_years", 10),
        wards=scenario.parameters.get("wards", ["Eastlands"]),
        parallel=True,
    )

    return scenario, gdf
