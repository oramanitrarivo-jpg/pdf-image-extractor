import os

# ─── Anthropic ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL   = "claude-sonnet-4-20250514"

# ─── Classification des images ─────────────────────────────────────────────────
CONFIDENCE_ACCEPT   = 0.80
MIN_IMAGE_BYTES     = 1500
MIN_IMAGE_DIMENSION = 75

# ─── Rendu des pages PDF ───────────────────────────────────────────────────────
PAGE_RENDER_DPI = 150

# ─── Types MIME ────────────────────────────────────────────────────────────────
EXT_MAP = {
    "png":  "image/png",
    "jpeg": "image/jpeg",
    "jpg":  "image/jpeg",
    "webp": "image/webp",
}
