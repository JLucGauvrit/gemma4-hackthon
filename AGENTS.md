# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.12+ research-debate prototype managed with `uv`.
Application code lives in `core/`: `pipeline.py` orchestrates the async flow,
`schema.py` defines the shared dataclass contract, `retrieve.py` handles
OpenAIRE evidence retrieval, `mcp_client.py` manages MCP/OAuth access, and
`llm.py` is the model integration seam. `main.py` is the top-level entry point.
Keep design notes, deployment guidance, and source PDFs in `docs/`; do not mix
them into runtime modules.

## Build, Test, and Development Commands

- `uv sync` installs the locked dependencies from `uv.lock`.
- `uv run python -m core.pipeline --selfcheck` runs the offline orchestration
  self-check. Use it before submitting pipeline or schema changes; it requires
  neither a model nor network access.
- `uv run python -m core.mcp_client openaire` performs the one-time browser
  authorization for live retrieval.
- `GEMMA_MODEL=gemma4:e4b uv run python -m core.pipeline "<claim>"` runs an
  end-to-end local demo. It requires Ollama, the selected Gemma model, and
  prior OpenAIRE authorization.

## Coding Style & Naming Conventions

Follow the existing Python style: four-space indentation, type annotations,
`snake_case` functions and variables, `PascalCase` dataclasses, and concise
module/function docstrings. Preserve the `core.schema` contract deliberately:
add or alter fields only when all pipeline stages are updated together. Keep
external model calls behind `core.llm.generate`; avoid provider-specific calls
in orchestration code. No formatter or linter is currently configured, so
match nearby code and keep imports grouped as standard library then local.

## Testing Guidelines

There is currently no separate test directory or coverage target. Extend the
pipeline self-check when changing pure logic such as citation enforcement,
evidence partitioning, asymmetry, or guardrails. Name new checks for the
behavior they verify and keep them deterministic and offline. Manually run a
live claim only when a change affects retrieval, OAuth, or model prompting.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style subjects, for example
`feat: add live research agent orchestration` and `docs: build notes`.
Use a focused imperative subject with an appropriate prefix (`feat`, `fix`,
`docs`, or `chore`). Pull requests should state the behavior changed, list
validation performed (at minimum the self-check when applicable), link related
issues or PRD sections, and include terminal output or screenshots for
user-visible workflow changes.

## Security & Configuration

Never commit OAuth refresh tokens, local Ollama configuration, or credentials.
The MCP client caches authorization outside the repository; keep it that way.
