# Gemini MCP

A Dockerized, HTTP-streamable [MCP](https://modelcontextprotocol.io) server that exposes the Google Gemini API as tools any MCP client (Claude Code, Claude Desktop, Cursor, etc.) can call.

## Tools

| Tool | Purpose |
|---|---|
| `generate_text` | Text generation with optional system instruction, temperature, max tokens, thinking budget |
| `generate_with_images` | Multimodal generation from paths / URLs / base64 images |
| `generate_with_files` | Multimodal generation from File API URIs (PDF, audio, video) |
| `chat` | Multi-turn conversation with caller-supplied history |
| `search_grounded_generate` | Generation grounded in live Google Search results, with citations |
| `analyze_url` | Generation grounded in the contents of one or more URLs |
| `code_execution` | Generation with Python sandbox — Gemini writes and runs code |
| `embed_text` | Embeddings via `gemini-embedding-001` (configurable) |
| `count_tokens` | Token count for a prompt against a given model |
| `list_models` | List available Gemini models and their limits |
| `upload_file` | Upload a local file to the Gemini File API |
| `list_files` | List uploaded files |
| `delete_file` | Delete an uploaded file |

## Setup

Requires Docker and a Gemini API key (https://aistudio.google.com/apikey).

```bash
cp .env.example .env
# edit .env: set GEMINI_API_KEY
docker compose up --build
```

Server listens at `http://localhost:3000/mcp`.

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | From Google AI Studio |
| `GEMINI_DEFAULT_MODEL` | `gemini-2.5-flash` | Default model for generation tools |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` | Default model for `embed_text` |
| `PORT` | `3000` | Host port for the streamable HTTP endpoint |

## Connect to Claude

**Claude Code:**

```bash
claude mcp add --transport http gemini http://localhost:3000/mcp
```

**Claude Desktop / Claude.ai:** Settings → Connectors → Add custom connector → paste `http://localhost:3000/mcp`.

## Verify

Smoke-test with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector --cli http://localhost:3000/mcp \
  --transport http --method tools/list
```

Call a tool:

```bash
npx @modelcontextprotocol/inspector --cli http://localhost:3000/mcp \
  --transport http --method tools/call \
  --tool-name generate_text --tool-arg prompt="Say hi in one word."
```

## Run without Docker

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=...
python server.py
```

## Deployment notes

- Container speaks **plain HTTP**. For anything beyond localhost, front it with a reverse proxy (Caddy, nginx, Traefik) terminating TLS.
- There is **no built-in auth** on `/mcp`. If you expose this publicly, add bearer auth at the proxy and treat the Gemini API key as a secret, not as access control.
- Healthcheck is a TCP probe on the listen port, not an MCP handshake — good enough for `docker compose` restart policies.
- File uploads (`upload_file`) read from the container filesystem. Mount the host directory you want to upload from:

  ```yaml
  volumes:
    - ./uploads:/app/uploads:ro
  ```

## License

MIT.
