"""
ScrapTrust Copilot — a domain assistant for scrap, waste and mineral analysis.

The LLM (Claude, OpenAI, Gemini or any OpenAI-compatible endpoint) is the
reasoning and conversation layer. Domain evidence comes from the project's own
unsupervised engines, exposed to the LLM as tools:

- waste images: DINOv2 embeddings + nearest-neighbour search + K-Means clusters
- mineral spectra: rule-based absorption engine + PCA/K-Means spectral model
- image quality: the existing evidence-quality heuristics
"""
