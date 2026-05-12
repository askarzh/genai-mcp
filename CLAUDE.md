# Gemini MCP Server — Agent Notes

HTTP-streamable MCP server that exposes the Google Gemini API as tools. Single-file Python, FastMCP, Dockerized.

## Stack

- **FastMCP 2.x** (`fastmcp`) — server framework, decorator-based tool registration
- **google-genai** (`from google import genai`) — official Gemini SDK (unified successor to `google-generativeai`)
- **Pydantic** — used only for the `ChatMessage` model so the `chat` tool gets a tight JSON schema
- **Python 3.12-slim** in Docker, non-root user, plain HTTP on `:3000/mcp`

## Layout

Everything lives in one file: `server.py`. Helpers at top, tools below, `mcp.run(...)` at bottom. Keep it that way unless the file exceeds ~500 LOC — premature splitting hurts readability here.

```
server.py            # all tools + helpers
requirements.txt     # 3 deps, pinned by minor
Dockerfile           # python:3.12-slim, non-root, TCP healthcheck
docker-compose.yml   # reads .env, exposes 3000
.env.example         # GEMINI_API_KEY, GEMINI_DEFAULT_MODEL, GEMINI_EMBED_MODEL, PORT
```

## Adding a tool

1. Decorate with `@mcp.tool(annotations={...})`. Use `readOnlyHint: True` for anything that doesn't mutate remote state; `destructiveHint: True` for deletes.
2. **Use type hints** — FastMCP derives the JSON schema from them. `list[str]`, `Optional[int]`, Pydantic models all work.
3. **The docstring becomes the tool description.** It lands in Claude's context window verbatim. Keep it terse, action-oriented, and call out non-obvious params.
4. Build `GenerateContentConfig` via the `_build_config` helper — don't reinvent kwargs assembly per tool.
5. Always return JSON-serializable dicts/lists. Include `model` and `usage` so callers can attribute cost.

## Tool-design rules already in effect

- **One tool per action**, ~13 tools total. Stay under 15 — beyond that the tool list pollutes Claude's context.
- **File-aware multimodal is split**: `generate_with_images` (inline bytes) vs `generate_with_files` (File API URIs). Don't merge them — small images shouldn't pay the upload roundtrip, large files shouldn't be base64'd.
- **Built-in Gemini tools (search/url/code) are exposed as separate MCP tools** rather than a single `generate` with toggles. Claude picks better when the choice is in the tool name.

## Auth model

Static API key from `GEMINI_API_KEY` env var, read once at module import. No per-request auth, no OAuth. If you ever expose this publicly, add bearer auth at the transport layer — don't rely on Gemini's key as the gate.

## Transport

`mcp.run(transport="http", host="0.0.0.0", port=PORT)` — streamable HTTP, stateless per request. The `/mcp` endpoint is the only MCP route; there is no separate health endpoint (Docker healthcheck does a TCP probe, not an MCP handshake).

## Testing

```bash
# Lint/parse
python3 -c "import ast; ast.parse(open('server.py').read())"

# Live tool listing (server must be running)
npx @modelcontextprotocol/inspector --cli http://localhost:3000/mcp \
  --transport http --method tools/list

# Call a tool
npx @modelcontextprotocol/inspector --cli http://localhost:3000/mcp \
  --transport http --method tools/call \
  --tool-name generate_text --tool-arg prompt="hello"
```

## Gotchas

- `thinking_budget` only applies to `gemini-2.5-*` models. Passing it to 1.5/2.0 will raise.
- `client.files.upload()` uploads from disk — the path must be readable by the container user (`app`). Volume-mount the source dir, don't rely on `/tmp` inside the container.
- Grounding metadata (`_extract_grounding`) silently returns `None` if the response shape changes between SDK versions. Don't depend on it being populated.
- `embed_content` returns one `Embedding` per input even when called with a single string — always iterate `response.embeddings`.

## What this server intentionally does not do

- **No streaming responses to the MCP client.** Tools return final text. MCP supports streamed tool output but Claude's UX for it is uneven; not worth the complexity here.
- **No `generate_json` / structured output tool.** Add one if a use case demands it; until then `generate_text` + post-parse is enough.
- **No context caching tool.** Useful for high-volume repeat prompts; add when needed.
- **No image generation (Imagen) tool.** Different SDK surface; out of scope for v1.
