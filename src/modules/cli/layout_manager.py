def list_layout_zones(layout_id: int) -> None:
    """Displays all configured pipelines/zones for a specific layout."""
    layout = store.layouts.get(layout_id)
    if not layout:
        print(f"Error: Layout ID {layout_id} not found.")
        return

    zones = store.zones.list_for_layout(layout_id)
    if not zones:
        print(f"\nNo pipelines/zones configured for layout '{layout.name}' (ID: {layout_id}).\n")
        return

    print(f"\n--- Zones / Pipelines for '{layout.name}' (ID: {layout_id}) ---")
    for z in zones:
        coords = f"C=({z.cx}, {z.cy}) R={z.r}" if z.zone_type == "CIRCLE" else f"Rect=({z.x1},{z.y1})->({z.x2},{z.y2})"
        cam_flag = " [MoveCam]" if z.move_camera else ""
        print(f"  [{z.id}] {z.name or 'Unnamed'} | Key: {z.scancode} | Type: {z.zone_type} | Prio: {z.priority} | {coords}{cam_flag}")
    print()
