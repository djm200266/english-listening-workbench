"""Unified style presets for ComfyUI image generation."""

STYLE_PRESETS = {
    "structured_schematic": {
        "label": "结构化示意图",
        "positive": "simple clean schematic diagram, clear labels, educational illustration, simple shapes and arrows",
        "negative": "photorealistic, complex textures, busy background, dark, blurry",
    },
    "textbook_cartoon": {
        "label": "教材卡通",
        "positive": (
            "middle school English textbook illustration, colorful cartoon style, "
            "clean outlines, simple shapes, bright but balanced colors, "
            "clear educational composition, suitable for Grade 7 students"
        ),
        "negative": (
            "photorealistic, dark atmosphere, horror, complex background, "
            "anime fan art, cinematic realism"
        ),
    },
    "watercolor": {
        "label": "水彩插画",
        "positive": (
            "soft watercolor illustration, visible watercolor paper texture, "
            "gentle pigment transitions, hand-painted educational illustration, "
            "clean composition, readable visual relationships"
        ),
        "negative": (
            "photorealistic, 3d render, glossy plastic, heavy oil painting, "
            "dark muddy colors, blurred structure"
        ),
    },
    "photorealistic": {
        "label": "写实风格",
        "positive": (
            "realistic photography style, natural lighting, realistic materials, "
            "clear details, believable environment, balanced composition"
        ),
        "negative": (
            "cartoon, anime, flat vector, watercolor, distorted perspective, overprocessed image"
        ),
    },
    "flat_vector": {
        "label": "扁平矢量",
        "positive": (
            "flat vector illustration, geometric shapes, clean edges, "
            "limited color palette, minimal shadows, clear infographic layout"
        ),
        "negative": (
            "photorealistic, watercolor texture, oil painting, noisy background, complex lighting"
        ),
    },
    "hand_drawn": {
        "label": "手绘风格",
        "positive": (
            "hand-drawn educational illustration, natural ink outlines, "
            "slightly imperfect handmade lines, warm classroom material style"
        ),
        "negative": (
            "photorealistic, sterile 3d render, glossy surface, excessive detail"
        ),
    },
    "comic": {
        "label": "漫画风格",
        "positive": (
            "educational comic illustration, expressive poses, clear panel layout, "
            "bold outlines, readable storytelling, bright colors"
        ),
        "negative": (
            "photorealistic, horror comic, dark noir, excessive action effects"
        ),
    },
    "colored_pencil": {
        "label": "彩色铅笔",
        "positive": (
            "colored pencil illustration, visible pencil strokes, soft handmade texture, "
            "warm educational artwork, clean and child-friendly"
        ),
        "negative": (
            "photorealistic, glossy 3d render, heavy watercolor bleed, dark colors"
        ),
    },
    "three_d_cartoon": {
        "label": "3D卡通",
        "positive": (
            "friendly 3D cartoon illustration, soft lighting, rounded shapes, "
            "colorful educational scene, clean composition"
        ),
        "negative": (
            "photorealistic human skin, horror, dark cinematic scene, uncanny characters"
        ),
    },
}


def get_style_preset(style: str) -> dict:
    # Map legacy styles
    legacy_map = {
        "cartoon": "textbook_cartoon", "children_book": "textbook_cartoon",
        "flat": "flat_vector", "realistic": "photorealistic",
    }
    resolved = legacy_map.get(style, style)
    return STYLE_PRESETS.get(resolved, STYLE_PRESETS["textbook_cartoon"])


def get_style_label(style: str) -> str:
    return STYLE_PRESETS.get(style, {}).get("label", style)
