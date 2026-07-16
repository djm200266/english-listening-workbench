"""
Topic classifier: auto-detect topic_type from script dialogue content.
Returns: directions | weather | story | fallback
"""

from __future__ import annotations
from models import DialogueScript


# ---- Keyword sets ----

DIRECTIONS_KEYWORDS = {
    "where is", "how can i get to", "how do i get to", "can you tell me the way",
    "turn left", "turn right", "go straight", "go along", "across from",
    "next to", "between", "behind", "in front of", "near", "nearby",
    "library", "bank", "hospital", "school", "post office", "supermarket",
    "hotel", "restaurant", "museum", "park", "station", "airport",
    "bookstore", "pharmacy", "bus stop", "train station",
    "street", "road", "corner", "block", "crosswalk", "intersection",
    "second floor", "first floor", "third floor",
    "five-minute walk", "ten-minute", "blocks away",
    "directions", "map", "location", "address", "landmark",
}

WEATHER_KEYWORDS = {
    "weather", "sunny", "rainy", "cloudy", "windy", "snowy", "foggy",
    "raining", "snowing", "storm", "thunderstorm", "lightning",
    "temperature", "degrees", "celsius", "fahrenheit",
    "hot", "cold", "warm", "cool", "freezing", "boiling",
    "umbrella", "raincoat", "coat", "sweater", "scarf",
    "forecast", "climate", "season", "summer", "winter", "spring", "autumn",
    "how is the weather", "what is the weather like",
    "sunshine", "breeze", "shower", "drizzle", "blizzard",
    "humid", "dry", "wet",
}

STORY_KEYWORDS = {
    "once upon a time", "long long ago", "story", "tell me a story",
    "fairy tale", "myth", "legend", "folktale",
    "mountain", "moved the mountains", "emperor", "king", "queen",
    "dragon", "magic", "witch", "wizard", "princess", "prince",
    "forest", "castle", "village", "kingdom",
    "brave", "clever", "kind", "evil", "giant",
    "happened", "then", "after that", "finally", "at last",
    "moral of the story", "once there was",
    "try to move", "tried to move", "decided to",
}


def classify_topic(script: DialogueScript) -> str:
    """
    Classify a dialogue script into topic_type:
      directions | weather | story | fallback

    Uses keyword density scoring. The category with the most keyword hits wins.
    """
    if not script or not script.dialogue:
        return "fallback"

    all_text = " ".join(t.text.lower() for t in script.dialogue)

    scores = {
        "directions": _count_hits(all_text, DIRECTIONS_KEYWORDS),
        "weather": _count_hits(all_text, WEATHER_KEYWORDS),
        "story": _count_hits(all_text, STORY_KEYWORDS),
    }

    # Also check task config scenario + vocab
    if script.used_vocabulary:
        vocab_text = " ".join(v.lower() for v in script.used_vocabulary)
        scores["directions"] += _count_hits(vocab_text, DIRECTIONS_KEYWORDS) * 2
        scores["weather"] += _count_hits(vocab_text, WEATHER_KEYWORDS) * 2
        scores["story"] += _count_hits(vocab_text, STORY_KEYWORDS) * 2

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "fallback"
    return best


def _count_hits(text: str, keywords: set[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


def get_image_spec(topic_type: str) -> dict:
    """Return image_type, style_preset, render_mode for a given topic_type."""
    specs = {
        "directions": {
            "image_type": "location_reference_map",
            "style_preset": "textbook_directions_map",
            "render_mode": "deterministic_map",
            "panel_count": 1,
            "default_size": {"width": 1024, "height": 768},
        },
        "weather": {
            "image_type": "weather_reference_scene",
            "style_preset": "textbook_weather_panel",
            "render_mode": "comfyui_direct",
            "panel_count": 1,  # may be overridden
            "default_size": {"width": 1024, "height": 768},
        },
        "story": {
            "image_type": "story_reference_illustration",
            "style_preset": "textbook_story_board",
            "render_mode": "comfyui_direct",
            "panel_count": 1,
            "default_size": {"width": 1024, "height": 768},
        },
        "fallback": {
            "image_type": "topic_scene_illustration",
            "style_preset": "default_teaching_style",
            "render_mode": "comfyui_direct",
            "panel_count": 1,
            "default_size": {"width": 1024, "height": 1024},
        },
    }
    return specs.get(topic_type, specs["fallback"])
