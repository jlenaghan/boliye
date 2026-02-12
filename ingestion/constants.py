"""Shared constants for the ingestion pipeline."""

# LLM generation defaults
DEFAULT_BATCH_SIZE = 20
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_TEMPERATURE_DETERMINISTIC = 0.2  # For classification tasks (CEFR, topics)
DEFAULT_EXTRACTION_TEMPERATURE = 0.3

# Document processing
DEFAULT_CHUNK_SIZE = 12000  # Max chars per LLM call for extraction

# Richness scoring weights (used in deduplication)
CONTEXT_WEIGHT = 2  # Context is highly valuable for learning
ROMANIZATION_BONUS = 10  # Having romanization is a fixed bonus
FAMILIARITY_SIGNAL_WEIGHT = 5  # Each familiarity signal adds value
