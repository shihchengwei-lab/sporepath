# Contributing

This is an early PoC. The most useful contributions are grounded in real local
usage, especially extraction quality and graph behavior.

## Good Issues

Please include:

- input format: ChatGPT export, Claude JSONL, Codex rollout JSONL, or other
- extractor: `rules` or `ollama`
- model name if using Ollama
- command used
- expected behavior
- actual behavior
- a short redacted sample when possible

Do not attach private chat exports. Reduce examples to the smallest safe
fragment that still reproduces the problem.

## Development

```powershell
python -m pip install -e .
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

Keep the core dependency-free for now. If a new dependency is needed, explain
why the Python standard library or existing browser runtime is not enough.

## Design Constraint

Small local models are scouts. They should propose candidate memory atoms, not
be trusted as the final memory authority. Promotion, sinking, and resurfacing
should remain driven by local rules and usage signals.
