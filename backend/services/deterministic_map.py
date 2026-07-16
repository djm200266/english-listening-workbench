"""
Deterministic location reference map generator using PIL.
Generates a simple but clear street map with landmarks, roads, and route arrows.
Works without ComfyUI.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont
import math
import os
from pathlib import Path
from datetime import datetime, timezone
from config import get_config


def _assets_dir(task_id: str) -> Path:
    root = get_config().get("assets", {}).get("rootDir", "storage")
    d = Path(root) / task_id / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_directions_map(
    task_id: str,
    landmarks: list[str],
    route_steps: list[str],
    start_label: str = "You are here",
    grade_label: str = "Grade 7",
) -> str:
    """
    Generate a simple location reference map.

    Args:
        task_id: Task ID for file naming
        landmarks: List of landmark names (e.g. ["Library", "Bank", "Hospital"])
        route_steps: Steps in the route (e.g. ["go straight", "turn left", "arrive"])
        start_label: Label for the starting point
        grade_label: Grade label for title (e.g. "七年级")

    Returns:
        Absolute path to the generated PNG file
    """
    width, height = 1024, 768
    img = Image.new("RGB", (width, height), "#FAFAF0")
    draw = ImageDraw.Draw(img)

    # Try to load a font, fall back to default
    try:
        font_title = ImageFont.truetype("arial.ttf", 28)
        font_label = ImageFont.truetype("arial.ttf", 16)
        font_small = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # ---- Draw title bar ----
    draw.rectangle([0, 0, width, 50], fill="#4A90D9")
    draw.text((20, 10), f"Location Reference Map - {grade_label}", fill="white", font=font_title)

    # ---- Layout: roads and landmarks ----
    margin = 60
    map_left = margin
    map_top = 80
    map_right = width - margin
    map_bottom = height - margin - 40
    map_width = map_right - map_left
    map_height = map_bottom - map_top

    # Draw a light background for the map area
    draw.rectangle([map_left, map_top, map_right, map_bottom], fill="#F0F8E8", outline="#888888", width=2)

    # Draw main roads as a grid
    road_color = "#CCCCCC"
    road_border = "#AAAAAA"
    v_roads = max(1, len(landmarks) // 2 + 1)
    h_roads = 2

    v_positions = []
    for i in range(v_roads + 1):
        x = int(map_left + (map_width / max(v_roads, 1)) * i)
        v_positions.append(x)
        draw.line([(x, map_top), (x, map_bottom)], fill=road_border, width=1)
        draw.line([(x - 8, map_top), (x + 8, map_bottom)], fill=road_color, width=14)

    h_positions = []
    for i in range(h_roads + 1):
        y = int(map_top + (map_height / h_roads) * i)
        h_positions.append(y)
        draw.line([(map_left, y), (map_right, y)], fill=road_border, width=1)
        draw.line([(map_left, y - 8), (map_right, y + 8)], fill=road_color, width=14)

    # Place landmarks at intersections + midpoints
    colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"]
    placed = []
    mid_x = (map_left + map_right) // 2
    mid_y = (map_top + map_bottom) // 2

    for idx, landmark in enumerate(landmarks[:8]):
        if idx == 0:
            # First landmark near top
            lx = mid_x
            ly = map_top + 100
        elif idx == 1:
            lx = map_left + 200
            ly = mid_y - 80
        elif idx == 2:
            lx = map_right - 200
            ly = mid_y - 80
        elif idx == 3:
            lx = mid_x
            ly = mid_y + 100
        elif idx == 4:
            lx = map_left + 250
            ly = map_top + 250
        elif idx == 5:
            lx = map_right - 250
            ly = map_bottom - 200
        elif idx == 6:
            lx = map_left + 150
            ly = map_bottom - 150
        elif idx == 7:
            lx = map_right - 150
            ly = map_top + 150
        else:
            lx = map_left + 100 + idx * 80
            ly = map_top + 300

        color = colors[idx % len(colors)]

        # Draw building block
        bw, bh = 70, 50
        draw.rectangle([lx - bw//2, ly - bh//2, lx + bw//2, ly + bh//2],
                       fill=color, outline="#333333", width=2)
        # Building label
        short_name = landmark[:14]
        draw.text((lx, ly + bh//2 + 5), short_name, fill="#333333", font=font_small, anchor="mt")

        placed.append((lx, ly, landmark, color))

    # ---- Draw route arrows ----
    if len(placed) >= 2:
        for i in range(len(placed) - 1):
            x1, y1, _, _ = placed[i]
            x2, y2, _, _ = placed[i + 1]
            _draw_arrow(draw, x1 + 35, y1, x2 - 35, y2, "#FF6600", 5)

        # Start marker
        sx, sy, _, _ = placed[0]
        draw.ellipse([sx - 12, sy - 12, sx + 12, sy + 12], fill="#00CC00", outline="#008800", width=2)
        draw.text((sx, sy - 20), start_label, fill="#008800", font=font_small, anchor="mb")

        # End marker
        ex, ey, _, _ = placed[-1]
        size = 10
        draw.polygon([
            (ex, ey - 14), (ex - 10, ey + 8), (ex + 10, ey + 8)
        ], fill="#FF0000", outline="#CC0000")
        draw.text((ex, ey + 24), "DESTINATION", fill="#CC0000", font=font_small, anchor="mt")

    # ---- Route steps legend ----
    legend_y = map_bottom + 8
    if route_steps:
        steps_text = "Route: " + " -> ".join(route_steps[:6])
        draw.text((map_left, legend_y), steps_text, fill="#555555", font=font_small)

    # ---- Save ----
    assets = _assets_dir(task_id)
    version = 1
    out_path = str(assets / f"image_v{version}.png")
    img.save(out_path, "PNG")

    # Save metadata
    meta = {
        "task_id": task_id, "image_type": "location_reference_map",
        "style_preset": "textbook_directions_map", "render_mode": "deterministic_map",
        "landmarks": landmarks, "route_steps": route_steps,
        "generated_at": _now_iso(), "comfyui_used": False,
    }
    import json
    meta_path = str(assets / f"image_v{version}_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return out_path


def _draw_arrow(draw, x1, y1, x2, y2, color, width):
    """Draw a directed arrow from (x1,y1) to (x2,y2)."""
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    arrow_len = 18
    ax1 = x2 - arrow_len * math.cos(angle - 0.4)
    ay1 = y2 - arrow_len * math.sin(angle - 0.4)
    ax2 = x2 - arrow_len * math.cos(angle + 0.4)
    ay2 = y2 - arrow_len * math.sin(angle + 0.4)
    draw.polygon([(x2, y2), (ax1, ay1), (ax2, ay2)], fill=color)
