# Deployment Recommendation

## Decision

Deploy the hackathon application on **NVIDIA Brev**, using:

- one Brev GPU instance;
- Gemma 4 E4B served through vLLM's OpenAI-compatible API;
- the orchestration application and UI on the same instance;
- only the application port exposed publicly;
- vLLM used as the inference backend in every environment;
- cached, verified research results as a fallback for the live demo.

This recommendation applies to the hackathon prototype. It is not a claim that
Brev is the best long-term production platform.

## Why Brev

### 1. It directly supports the submission requirements

The hackathon requires a demo reachable by someone other than the builder.
Brev can expose an HTTP service through a secure link or public port, so the
judges can access the application without reproducing the local environment.

The event documentation also presents Brev as the intended path to NVIDIA GPU
compute. Using it reduces the risk of spending hackathon time configuring
drivers, CUDA, networking, and a separate hosting provider.

References:

- [NVIDIA Brev core concepts](https://docs.nvidia.com/brev/latest/concepts/overview)
- [NVIDIA Brev Launchables](https://docs.nvidia.com/brev/concepts/launchables)
- [NVIDIA Brev connectivity](https://docs.nvidia.com/brev/cli/connectivity)

### 2. It strengthens the Gemma integration story

The application should execute Gemma locally on an NVIDIA GPU rather than call
a closed hosted model. This makes Gemma load-bearing and makes the model,
precision, hardware, latency, and concurrency measurable.

Brev also makes the project eligible for the separate NVIDIA GPU challenge if
we use one of the accepted inference frameworks and document:

- framework choice;
- hardware and model variant;
- precision and concurrency;
- an end-to-end optimization;
- a reproducible benchmark against a meaningful baseline.

### 3. It keeps the demo architecture small

One GPU instance can host both inference and the application. This avoids
cross-provider networking, an externally exposed model API, and two separate
deployment procedures.

For the hackathon, operational simplicity is more valuable than horizontal
scalability.

## Proposed Architecture

```text
Browser
  |
  v
Application/UI :7860
  |
  +--> Devil's Advocates orchestration
  |      |
  |      +--> Alien research MCPs
  |      +--> cached demo evidence fallback
  |
  +--> Gemma 4 API :8000
          |
          +--> vLLM
          +--> Gemma 4 E4B
```

Only port `7860` should be exposed. The model server on port `8000` should
remain private to the instance.

The application may initially use Gradio because it supports a usable streamed
demo with little deployment code. If the existing frontend is ready, it can
call a FastAPI orchestration service instead.

## Why vLLM Instead of Ollama on Brev

vLLM is the selected backend for both local development and Brev because:

- it exposes a standard OpenAI-compatible API;
- it is one of the frameworks named by the NVIDIA challenge;
- it supports batching and production-oriented serving metrics;
- it provides a stronger optimization and benchmarking story;
- the orchestration code can remain independent of the concrete model server.

The model boundary should therefore support at least:

```text
stub -> vLLM/OpenAI-compatible API
```

The same pipeline should run against each backend without changing its domain
logic.

## Model Strategy

Start with **one Gemma 4 E4B checkpoint** for every role:

| Role | Model | Thinking |
|---|---|---|
| Claim extraction | E4B | off |
| Stance classification | E4B | off |
| Advocates | E4B | off |
| Citation verification | E4B | off |
| Judge | E4B | on |

This is an honest single-checkpoint deployment with role-specific inference
behavior.

Do not block deployment on E2B. Add a second tier only after:

1. the application works end to end;
2. the Gemma 4 E2B checkpoint is installed;
3. the serving framework handles both variants correctly;
4. latency and memory have been measured.

Do not claim that E2B is dynamically extracted from the loaded E4B checkpoint
unless that exact behavior is demonstrated with the selected Gemma 4 serving
stack.

## GPU Choice

Prefer an **L40S 48 GB** instance when available. It provides enough margin for
the E4B checkpoint, runtime overhead, long contexts, and concurrent requests.

A 24 GB GPU may work depending on model precision and server configuration,
but it leaves less margin. The local Ollama model size is not a reliable
estimate for vLLM BF16 memory use because Ollama may use a quantized artifact.

Record the actual:

- GPU model;
- checkpoint identifier;
- precision or quantization;
- maximum context length;
- concurrency;
- peak GPU memory;
- tokens per second;
- end-to-end latency.

## Alien Authentication

The installed Claude Code `openscience@alien` plugin proves that the research
tools are usable, but its OAuth session belongs to Claude Code. It is not
automatically available to the Python application running on Brev.

Before deployment, obtain one supported application authentication path:

1. an Alien-issued service token;
2. the documented OAuth flow for a standalone MCP client; or
3. an Alien backend `oat_` token.

Credentials must be supplied as runtime secrets and must not be committed.
Brev Launchable parameters can pass launch-time values, but reusable production
credentials should use an appropriate secret manager.

## Demo Reliability

The live demo must not depend completely on external retrieval availability.
Maintain a cached evidence package for at least:

- one genuinely contested biomedical claim;
- one consensus claim;
- optionally one asymmetric or low-evidence claim.

The UI and output must identify the retrieval mode:

```text
LIVE
CACHED FALLBACK
STUB
```

Stub mode must never look like a real scientific result.

For arbitrary unsupported input, such as "How many windows are in Paris?", the
pipeline must return an out-of-scope result rather than manufacture a debate.

## Brev Deployment Mode

### First deployment: VM mode

Use VM mode to reach a working deployment quickly:

1. create a Brev GPU instance;
2. clone the public repository;
3. install the project with `uv`;
4. install and start vLLM;
5. start the orchestration application;
6. add a Brev tunnel or secure link for port `7860`;
7. verify access from a separate browser session.

VM mode is appropriate while commands and model settings are still changing.

### Reproducible deployment: Docker Compose or Launchable

After the VM deployment works, capture it as either:

- a Docker Compose configuration with separate `model` and `app` services; or
- a Brev Launchable referencing the repository and setup script.

A Launchable can declare hardware, source, setup, network configuration, and
launch parameters. This is valuable for the writeup and NVIDIA challenge, but
it should not delay the first live URL.

Do not use Kubernetes for the hackathon prototype. It adds deployment work
without improving the judging experience.

## Readiness Gates

The deployment is ready only when all of these pass:

### Health

```text
model_ready=true
retrieval_ready=true | cached_fallback=true
mode=live | cached
```

### Scientific question

The output must contain:

- question-dependent evidence;
- question-dependent claims;
- valid per-claim citations;
- a question-dependent crux;
- a visible retrieval mode.

### Consensus question

The application must avoid manufacturing a balanced controversy and describe
the retrieved evidence as asymmetric.

### Unsupported question

The application must return an explicit out-of-scope response.

### External access

The public URL must be tested:

- outside the Brev instance;
- in a fresh browser session;
- without local port forwarding;
- using the same link placed in the submission.

## Build Order

1. Make stub mode explicit in CLI and UI output.
2. Configure `core/llm.py` with the served vLLM model name and endpoint.
3. Configure the installed Gemma 4 E4B model correctly.
4. Add claim-domain validation.
5. Connect authenticated Alien retrieval.
6. Add cached, verified retrieval fixtures.
7. Implement stance classification.
8. Implement claim-to-passage citation verification.
9. Stream pipeline events through the application API.
10. Deploy the first working version to a Brev VM.
11. Expose and externally test the application URL.
12. Record benchmarks and a backup demo video.
13. Convert the working setup into Compose or a Launchable if time remains.

## Alternatives Considered

### Local machine plus tunnel

Fast, but fragile and inconsistent with the requirement that the demo remain
reachable independently of the builder's machine. It also weakens the NVIDIA
deployment story.

### CPU application host plus remote GPU API

Operationally more complex. It introduces another provider, network latency,
API authentication, and an externally exposed inference endpoint.

### Hosted model API

Fast to integrate, but makes Gemma less visibly load-bearing and can fail the
submission requirement if a closed model performs the meaningful work.

### Ollama on Brev

Not selected for this project. vLLM provides the OpenAI-compatible endpoint,
batching, and serving metrics required by the deployment plan.

## Final Recommendation

Use Brev as a GPU-backed application host, not merely as a remote shell.
Serve one Gemma 4 E4B checkpoint with vLLM, keep inference private, expose the
streamed application, authenticate Alien independently of Claude Code, and
retain cached verified evidence for demo recovery.

The immediate objective is a narrow, real, externally reachable workflow.
Two-tier serving, Launchables, and deeper optimization are follow-on work after
that workflow is reliable.
