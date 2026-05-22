"""Smoke test: call MCP tools through the in-process FastMCP client surface."""
import asyncio
import json

from aamp.mcp_server import mcp


async def main() -> None:
    result = await mcp.call_tool("list_destinations", {})
    # Per MCP spec, result is a list of content items (TextContent).
    for item in result:
        text = getattr(item, "text", None) or str(item)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(text[:400])
            continue
        if isinstance(data, list):
            print(f"list_destinations -> {len(data)} destinations")
            for d in data:
                name = d.get("name") or f"#{d['id']}"
                print(f"  - {name} (id={d['id']}, members={d['member_physical_zone_ids']})")
        else:
            print(json.dumps(data, indent=2)[:400])

    print()
    result = await mcp.call_tool("describe_one_destination", {"destination_id": 2})
    for item in result:
        text = getattr(item, "text", None) or str(item)
        print(text)


if __name__ == "__main__":
    asyncio.run(main())
