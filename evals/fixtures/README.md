# Recorded model responses

Fixtures for `warrant/llm.py` in `replay` mode, keyed by a hash of the purpose, model,
system prompt, user prompt and response schema.

Record them by running with a real key:

```bash
WARRANT_LLM_MODE=live WARRANT_RECORD_FIXTURES=true ANTHROPIC_API_KEY=... make eval
```

The directory is empty on purpose. Every model call degrades to the deterministic path on a
fixture miss, so `make eval` and CI run offline and reproducibly with nothing here — the
numbers in the README were produced with this directory empty.
