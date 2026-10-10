"""Spawns server.py over stdio with the official MCP client and drives a few tools end to end."""
import json
import sys
from pathlib import Path

import anyio
import pytest

pytestmark = pytest.mark.blender
SERVER = Path(__file__).resolve().parents[1] / "server.py"


async def _session_run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            out = {"tools": tools}
            out["room"] = await session.call_tool("create_room", {
                "width_m": 4.5, "depth_m": 4.0, "height_m": 2.5,
                "openings": [{"kind": "door", "wall": "front", "offset_m": 1.0, "width_m": 0.9}]})
            out["sofa"] = await session.call_tool("instantiate_furniture", {
                "object_id": "mcp-sofa", "category": "sofa",
                "dimensions_m": {"width": 2.0, "depth": 0.9, "height": 0.8}, "position_m": [0, 0, -1.5]})
            out["bad"] = await session.call_tool("instantiate_furniture", {
                "object_id": "mcp-bad", "category": "sofa",
                "dimensions_m": {"width": 50, "depth": 0.9, "height": 0.8}})
            out["form_bad"] = await session.call_tool("instantiate_furniture", {
                "object_id": "mcp-form-bad", "category": "sofa",
                "dimensions_m": {"width": 2.0, "depth": 0.9, "height": 0.8}, "form": {"arm_style": "spaceship"}})
            out["form_wrong_cat"] = await session.call_tool("instantiate_furniture", {
                "object_id": "mcp-form-bad2", "category": "sofa",
                "dimensions_m": {"width": 2.0, "depth": 0.9, "height": 0.8}, "form": {"headboard": "tufted"}})
            out["form_set"] = await session.call_tool("set_dimensions_and_material", {
                "object_id": "mcp-sofa", "form": {"arm_style": "rolled", "surface": "velvet"}})
            out["form_set_bad"] = await session.call_tool("set_dimensions_and_material", {
                "object_id": "mcp-sofa", "form": {"arm_style": "spaceship"}})
            out["validate"] = await session.call_tool("validate_scene", {})
            out["preview"] = await session.call_tool("render_preview", {
                "filename": "mcp_test.png", "width_px": 128, "height_px": 96})
            out["export"] = await session.call_tool("export_asset", {
                "target": "mcp-sofa", "filename": "mcp_test_sofa.usdz"})
            await session.call_tool("reset_scene", {})
            return out


def _payload(result):
    if getattr(result, "structuredContent", None):
        sc = result.structuredContent
        return sc.get("result", sc)
    return json.loads(next(c.text for c in result.content if c.type == "text"))


def test_mcp_tools_end_to_end(blender_bin):
    out = anyio.run(_session_run)
    tools = out["tools"]
    expected = {"create_room", "instantiate_furniture", "set_dimensions_and_material", "set_transform",
                "validate_scene", "render_preview", "export_asset", "build_product_asset"}
    assert expected <= set(tools)
    dims_schema = json.dumps(tools["instantiate_furniture"].input_schema if hasattr(tools["instantiate_furniture"], "input_schema")
                             else tools["instantiate_furniture"].inputSchema)
    assert '"maximum": 5.0' in dims_schema and '"minimum": 0.003' in dims_schema
    for value in ('"bed"', '"nightstand"', '"dresser"', '"desk"', '"round"', '"rect"'):
        assert value in dims_schema, value
    product_schema = json.dumps(getattr(tools["build_product_asset"], "inputSchema", None)
                                or tools["build_product_asset"].input_schema)
    assert "nightstand" in product_schema and "round" in product_schema
    for name in ("instantiate_furniture", "set_dimensions_and_material", "build_product_asset"):
        schema = json.dumps(getattr(tools[name], "inputSchema", None) or tools[name].input_schema)
        for key in ("texture_path", "texture_mode", "texture_tile_m", '"print"', '"tile"'):
            assert key in schema, (name, key)
        assert '"form"' in schema and "arm_style" in schema and "headboard" in schema and "velvet" in schema, name
    assert not out["room"].is_error and not out["sofa"].is_error
    assert out["bad"].is_error
    assert out["form_bad"].is_error and "arm_style" in out["form_bad"].content[0].text
    assert out["form_wrong_cat"].is_error and "unknown keys" in out["form_wrong_cat"].content[0].text
    assert not out["form_set"].is_error
    assert _payload(out["form_set"])["form"] == {"arm_style": "rolled", "surface": "velvet"}
    assert out["form_set_bad"].is_error
    assert _payload(out["validate"])["ok"] is True
    assert not out["preview"].is_error and any(c.type == "image" for c in out["preview"].content)
    assert _payload(out["export"])["max_abs_error_m"] <= 0.001
