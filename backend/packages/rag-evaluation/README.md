# rag-evaluation

Evaluation runner for SEC filings RAG. Owns the per-case scoring helpers,
RAGAS metric stack (faithfulness, answer relevancy, context
precision/recall), the OpenAI client RAGAS uses to judge generated answers,
and the ablation analysis utilities.

Imported in-process by the API (`rag-benchmarking`). The launcher in
`rag_benchmarking.evaluation.runner` spawns a daemon thread per evaluation
that calls `rag_evaluation.runner.run_evaluation` directly — no Celery
broker, no separate worker container.
