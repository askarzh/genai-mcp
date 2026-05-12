import base64
import mimetypes
import os
import urllib.request
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is required")

DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
DEFAULT_EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")

client = genai.Client(api_key=GEMINI_API_KEY)

mcp = FastMCP(
    name="gemini",
    instructions=(
        "Tools for Google Gemini. "
        "For multi-turn dialog pass prior turns to `chat`. "
        "For answers grounded in the live web use `search_grounded_generate`. "
        "To analyze specific web pages use `analyze_url`. "
        "For numeric/data tasks needing computation use `code_execution`. "
        "Large files (PDF, audio, video) should be sent via `upload_file` first, "
        "then referenced by URI in `generate_with_files`."
    ),
)


def _usage(response) -> Optional[dict]:
    u = getattr(response, "usage_metadata", None)
    if not u:
        return None
    return {
        "prompt_tokens": getattr(u, "prompt_token_count", None),
        "output_tokens": getattr(u, "candidates_token_count", None),
        "total_tokens": getattr(u, "total_token_count", None),
        "thoughts_tokens": getattr(u, "thoughts_token_count", None),
    }


def _build_config(
    system_instruction: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
    tools: Optional[list] = None,
) -> Optional[types.GenerateContentConfig]:
    kwargs: dict = {}
    if system_instruction:
        kwargs["system_instruction"] = system_instruction
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    if thinking_budget is not None:
        kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=thinking_budget)
    if tools:
        kwargs["tools"] = tools
    return types.GenerateContentConfig(**kwargs) if kwargs else None


def _load_image_part(image: str) -> types.Part:
    if image.startswith(("http://", "https://")):
        with urllib.request.urlopen(image, timeout=30) as r:
            data = r.read()
            mime = r.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        return types.Part.from_bytes(data=data, mime_type=mime)
    p = Path(image)
    if p.exists():
        mime, _ = mimetypes.guess_type(str(p))
        return types.Part.from_bytes(data=p.read_bytes(), mime_type=mime or "image/jpeg")
    raw = base64.b64decode(image)
    return types.Part.from_bytes(data=raw, mime_type="image/jpeg")


def _extract_grounding(response) -> Optional[dict]:
    try:
        meta = response.candidates[0].grounding_metadata
    except (AttributeError, IndexError):
        return None
    if not meta:
        return None
    sources = []
    for c in getattr(meta, "grounding_chunks", []) or []:
        web = getattr(c, "web", None)
        if web:
            sources.append({"uri": web.uri, "title": web.title})
    return {
        "queries": list(getattr(meta, "web_search_queries", []) or []),
        "sources": sources,
    }


class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'model'")
    text: str


@mcp.tool(annotations={"readOnlyHint": True})
def generate_text(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system_instruction: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    thinking_budget: Optional[int] = None,
) -> dict:
    """Generate text from Gemini.

    thinking_budget: 0 disables thinking, -1 lets the model decide, positive integer caps thinking tokens.
    Only applies to thinking-capable models (gemini-2.5-*).
    """
    config = _build_config(
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking_budget=thinking_budget,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return {"text": response.text, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def generate_with_images(
    prompt: str,
    images: list[str],
    model: str = DEFAULT_MODEL,
    system_instruction: Optional[str] = None,
) -> dict:
    """Generate against one or more images.

    Each `images` entry may be a local file path, an https URL, or a raw base64 string.
    """
    parts: list = [_load_image_part(img) for img in images]
    parts.append(prompt)
    config = _build_config(system_instruction=system_instruction)
    response = client.models.generate_content(model=model, contents=parts, config=config)
    return {"text": response.text, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def generate_with_files(
    prompt: str,
    file_uris: list[str],
    model: str = DEFAULT_MODEL,
    system_instruction: Optional[str] = None,
) -> dict:
    """Generate against files previously uploaded via `upload_file`.

    Each entry is a file resource name (e.g. 'files/abc123') returned by upload_file.
    Supports PDFs, audio, video, and images.
    """
    parts: list = []
    for uri in file_uris:
        f = client.files.get(name=uri)
        parts.append(types.Part.from_uri(file_uri=f.uri, mime_type=f.mime_type))
    parts.append(prompt)
    config = _build_config(system_instruction=system_instruction)
    response = client.models.generate_content(model=model, contents=parts, config=config)
    return {"text": response.text, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def chat(
    messages: list[ChatMessage],
    model: str = DEFAULT_MODEL,
    system_instruction: Optional[str] = None,
    temperature: Optional[float] = None,
) -> dict:
    """Multi-turn conversation. Pass full history as messages with role='user' or 'model'."""
    contents = [
        types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in messages
    ]
    config = _build_config(system_instruction=system_instruction, temperature=temperature)
    response = client.models.generate_content(model=model, contents=contents, config=config)
    return {"text": response.text, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def search_grounded_generate(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Generate with Google Search grounding. Returns text plus cited web sources."""
    config = _build_config(tools=[types.Tool(google_search=types.GoogleSearch())])
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    return {
        "text": response.text,
        "model": model,
        "grounding": _extract_grounding(response),
        "usage": _usage(response),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def analyze_url(prompt: str, urls: list[str], model: str = DEFAULT_MODEL) -> dict:
    """Analyze the content of one or more URLs. Gemini fetches each URL and grounds the response on it."""
    full_prompt = f"{prompt}\n\nURLs:\n" + "\n".join(urls)
    config = _build_config(tools=[types.Tool(url_context=types.UrlContext())])
    response = client.models.generate_content(model=model, contents=full_prompt, config=config)
    return {"text": response.text, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def code_execution(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Generate with code execution enabled. Gemini writes and runs Python in a sandbox.

    Returns the interleaved text, generated code, and execution results.
    """
    config = _build_config(tools=[types.Tool(code_execution=types.ToolCodeExecution())])
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    out: list[dict] = []
    for cand in response.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if getattr(part, "text", None):
                out.append({"type": "text", "value": part.text})
            ec = getattr(part, "executable_code", None)
            if ec:
                out.append({"type": "code", "language": str(ec.language), "value": ec.code})
            er = getattr(part, "code_execution_result", None)
            if er:
                out.append({"type": "result", "outcome": str(er.outcome), "value": er.output})
    return {"parts": out, "model": model, "usage": _usage(response)}


@mcp.tool(annotations={"readOnlyHint": True})
def embed_text(
    texts: list[str],
    model: str = DEFAULT_EMBED_MODEL,
    task_type: Optional[str] = None,
    output_dimensionality: Optional[int] = None,
) -> dict:
    """Generate embeddings for one or more texts.

    task_type examples: RETRIEVAL_QUERY, RETRIEVAL_DOCUMENT, SEMANTIC_SIMILARITY,
    CLASSIFICATION, CLUSTERING, QUESTION_ANSWERING, FACT_VERIFICATION, CODE_RETRIEVAL_QUERY.
    """
    cfg_kwargs: dict = {}
    if task_type:
        cfg_kwargs["task_type"] = task_type
    if output_dimensionality is not None:
        cfg_kwargs["output_dimensionality"] = output_dimensionality
    config = types.EmbedContentConfig(**cfg_kwargs) if cfg_kwargs else None
    response = client.models.embed_content(model=model, contents=texts, config=config)
    vectors = [e.values for e in response.embeddings]
    return {
        "embeddings": vectors,
        "model": model,
        "dimensions": len(vectors[0]) if vectors else 0,
        "count": len(vectors),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def count_tokens(prompt: str, model: str = DEFAULT_MODEL) -> dict:
    """Return the token count for a prompt against the given model. Does not generate."""
    response = client.models.count_tokens(model=model, contents=prompt)
    return {"total_tokens": response.total_tokens, "model": model}


@mcp.tool(annotations={"readOnlyHint": True})
def list_models() -> list[dict]:
    """List available Gemini models with their token limits and supported actions."""
    out: list[dict] = []
    for m in client.models.list():
        out.append({
            "name": m.name,
            "display_name": getattr(m, "display_name", None),
            "description": getattr(m, "description", None),
            "input_token_limit": getattr(m, "input_token_limit", None),
            "output_token_limit": getattr(m, "output_token_limit", None),
            "supported_actions": list(getattr(m, "supported_actions", []) or []),
        })
    return out


@mcp.tool()
def upload_file(file_path: str, display_name: Optional[str] = None) -> dict:
    """Upload a local file to the Gemini File API. Returns a resource name usable in generate_with_files.

    Supports PDFs, audio (mp3/wav/...), video (mp4/mov/...), and images.
    Files persist for 48 hours by default.
    """
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    config = types.UploadFileConfig(display_name=display_name) if display_name else None
    f = client.files.upload(file=str(p), config=config)
    return {
        "name": f.name,
        "uri": f.uri,
        "mime_type": f.mime_type,
        "size_bytes": f.size_bytes,
        "state": str(f.state),
    }


@mcp.tool(annotations={"readOnlyHint": True})
def list_files() -> list[dict]:
    """List files currently uploaded to the Gemini File API."""
    return [
        {
            "name": f.name,
            "uri": f.uri,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "state": str(f.state),
            "display_name": getattr(f, "display_name", None),
        }
        for f in client.files.list()
    ]


@mcp.tool(annotations={"destructiveHint": True})
def delete_file(name: str) -> dict:
    """Delete an uploaded file by its resource name (e.g. 'files/abc123')."""
    client.files.delete(name=name)
    return {"deleted": name}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "3000")),
    )
