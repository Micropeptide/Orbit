# Models

Orbit speaks three protocols. Everything above that layer is identical, so a
chat behaves the same whichever model answers.

| Kind | Wire | Used by |
|---|---|---|
| `openai` | `POST /v1/chat/completions` | MTPLX, Ollama, LM Studio, OpenAI, OpenRouter, Groq, DeepSeek, most self-hosted servers |
| `anthropic` | Messages API, official SDK | Claude with an API key |
| `cli` | a subprocess emitting JSON events | `claude`, `codex`, `opencode`, `qwen` |

## Choosing per chat

The picker sits at the top of every conversation. What you choose is stored with
that chat, so reopening it uses the same model, and each answer is labelled with
the model that produced it.

Three chats can generate at once. A fourth is told to wait rather than queued
silently.

## CLI agents — no API key

If you are signed into `claude` or `codex` in your terminal, Orbit can use them:
it spawns the CLI, streams its JSON events, and bills against that subscription.

Two things to know:

- **They are agents, not raw models.** `claude --print` arrives with its own
  Read/Bash/WebSearch tools and your MCP servers. Orbit's tools are not offered
  to it. Anything needing approval is auto-denied, because a non-interactive run
  has nobody to ask.
- **Each turn re-sends the conversation** as a labelled transcript, since a
  one-shot invocation has no memory. Fine for chat; long threads cost more per
  turn than they would in an API session.

Orbit never passes `--dangerously-skip-permissions`.

## Hosted APIs

Settings → Models & keys. Paste a key, press *fetch models*, and the provider's
catalogue appears in the picker. Keys are stored in `config/secrets.json`
(chmod 600).

The Anthropic path uses the Messages API directly rather than a compatibility
shim, so thinking blocks and tool calls arrive as themselves. Adaptive thinking
and effort are sent only to models that accept them.

Adding your own provider takes a base URL and a key name — anything
OpenAI-compatible works, including a vLLM or SGLang server on a lab machine.

## The local model

Orbit drives [MTPLX](https://github.com/Youssofal/MTPLX), which serves MLX models
on Apple Silicon with MTP speculative decoding. The server starts on demand and
stops after `idle_min` minutes.

Settings → Local server:

| Flag | What it does |
|---|---|
| Context window | Bigger allows longer chats; the KV cache grows with it |
| KV quantization | `q8` halves KV memory at near-zero quality cost |
| Draft depth | MTP speculative decoding depth; `mtplx tune` finds the best for your Mac |
| SSD session cache | Persists prefixes across restarts — a cold prefill drops from ~35s to ~3s |
| Fan mode | `smart` keeps a laptop quiet at the cost of a little throughput |

To use a different local model, download it through MTPLX and pick it in the
model picker — Orbit rewrites the launch config and restarts the server for you.
