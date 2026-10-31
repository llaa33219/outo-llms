# Anthropic translation layer for engines without native support

## Goal
Make `/v1/messages` work on ALL engines including llama-cpp-python (pip mode),
which has NO native /v1/messages endpoint. Translate Anthropic<->OpenAI in the
proxy for such engines instead of failing.

## Findings (verified against upstream sources)
- vLLM (>=0.19 incl v0.32.0): native /v1/messages + count_tokens. OK.
- SGLang (v0.5.22): native /v1/messages + count_tokens. OK.
- llama.cpp binary (llama-server): native /v1/messages + count_tokens. OK.
- llama-cpp-python (pip mode): ONLY /v1/chat/completions, /v1/completions,
  /v1/embeddings, /v1/models. NO /v1/messages. BROKEN.

## Design
- New adapter flag: EngineAdapter.supports_anthropic (ClassVar bool, default True).
  LlamaCppAdapter: binary=True -> True; binary=False (pip) -> False.
- Proxy: when protocol=anthropic and adapter.supports_anthropic is False,
  translate request to OpenAI chat/completions, forward, translate response back.
  This covers /v1/messages. count_tokens: translate to OpenAI /extras/tokenize/count
  (llama-cpp-python has it) or return error if unavailable.
- Translation module: src/outo_llms/server/anthropic_translate.py (pure functions,
  testable without server).

## Translation rules (Anthropic -> OpenAI)
- system (str|blocks) -> system message prepended to messages
- messages content blocks -> OpenAI content (text parts only for text)
- max_tokens -> max_tokens
- stop_sequences -> stop
- temperature/top_p -> same; top_k -> drop (no OpenAI equiv)
- tools (Anthropic {name,description,input_schema}) -> OpenAI functions format
- tool_choice -> map to OpenAI tool_choice
- stream -> same
Response (OpenAI -> Anthropic):
- choices[0].message.content -> content[{type:text,text}]
- finish_reason: stop->end_turn, length->max_tokens, tool_calls->tool_use
- usage.prompt_tokens/completion_tokens -> usage.input_tokens/output_tokens
- tool_calls -> content[{type:tool_use,...}]

## Steps
- [x] adapter flag + manager accessor
- [x] translation module (request + response, pure)
- [x] proxy integration for non-streaming
- [x] proxy integration for streaming (OpenAI SSE -> Anthropic SSE)
- [x] static checks + unit-style simulation tests
