# Contracts for the next milestones

Product: id, exact variant, category, image reference, price_cents, currency, dimensions_m {width,height,depth}, source_url, source_type, retrieved_at. Unknown dimensions remain unknown. The native prototype fixtures and backend fixtures are separate for now; connect the client before treating one as authoritative.

Scene item: product_id, asset_url, position_m [x,y,z], rotation, proposal_version. Canonical space is meters, Y-up, floor-centered origin. AR session alignment is separate.

Proposal: immutable version, selected products, known subtotal, unknown costs, shares by member, approvals by member. All changed items, totals, or splits require new approval.

Photon adapter: verified inbound identity + stable event ID -> backend decision. Ignore outbound events; deduplicate retries. The app's initial finance rules do not yet authenticate network messages.

Nessie adapter: authorized operation -> persisted job -> submit once -> reconcile confirmed/pending/failed/unknown. No blind retry after ambiguous timeouts. API response semantics and IDs must be validated before implementing remote writes.

Blender MCP: create_room, instantiate_furniture, set_transform, validate_scene, export_asset. Restrict parameter shapes and bounds; do not expose arbitrary model-generated Python as the first tool interface.

Gemini/LangGraph: retrieve -> filter -> rank -> lay out -> validate -> publish -> collect approvals. Financial authorization remains application code, not model judgment.
