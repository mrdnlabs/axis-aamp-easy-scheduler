"""Smoke check: Gemini tool conversion + system prompt load. No API calls."""
import asyncio
import json
from aamp.chat import (
    load_gemini_tools, load_system_prompt, DEFAULT_SYSTEM_PROMPT_PATH,
    sanitize_schema, detect_api_key,
)


async def smoke() -> None:
    tools = await load_gemini_tools()
    assert tools and tools[0].function_declarations
    decls = tools[0].function_declarations
    print(f"function_declarations loaded: {len(decls)}")
    for d in decls[:6]:
        desc = (d.description or "").splitlines()[0][:80] if d.description else ""
        print(f"  - {d.name}: {desc}")
    print(f"  ... ({len(decls) - 6} more)")

    # Sample a real tool with arguments so we can confirm properties survived sanitization.
    sample = next((d for d in decls if d.name == "create_destination"), decls[0])
    print(f"\nSample tool schema for '{sample.name}':")
    print(json.dumps(sample.parameters_json_schema, indent=2)[:800])

    prompt = load_system_prompt(DEFAULT_SYSTEM_PROMPT_PATH)
    print(f"\nsystem prompt: {len(prompt)} chars")
    print(f"  first line: {prompt.splitlines()[0][:90]}")

    print()
    print("API key in env:", "yes" if detect_api_key() else "NO (set GEMINI_API_KEY or GOOGLE_API_KEY)")

    # Verify a couple of MCP schemas don't carry unsupported keys
    raw_with_extras = {
        "type": "object",
        "additionalProperties": False,
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ShouldBeStripped",
        "properties": {"x": {"type": "integer", "description": "kept"}},
        "required": ["x"],
    }
    sanitized = sanitize_schema(raw_with_extras)
    assert "additionalProperties" not in sanitized
    assert "$schema" not in sanitized
    assert "title" not in sanitized
    assert sanitized["properties"]["x"]["type"] == "integer"
    print("\nsanitize_schema: extras stripped correctly")


if __name__ == "__main__":
    asyncio.run(smoke())
