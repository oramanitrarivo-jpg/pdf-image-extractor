import json
import logging
import base64

import anthropic

from config import ANTHROPIC_MODEL, CONFIDENCE_ACCEPT, EXT_MAP
from models.image import Image
from prompts.classify_prompt import PROMPT_CLASSIFY
from utils.json_helpers import clean_json_response


def classify(client: anthropic.Anthropic, raw_image: dict) -> Image:
    """
    Classifie une image extraite du PDF via Claude Vision.
    Retourne une Image enrichie avec confidence, category, reason et accepted.
    """
    media_type = EXT_MAP.get(raw_image["ext"].lower(), "image/png")
    data_b64   = base64.standard_b64encode(raw_image["image"]).decode()

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=256,
        system=PROMPT_CLASSIFY,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": media_type,
                        "data":       data_b64,
                    },
                },
                {
                    "type": "text",
                    "text": "Est-ce une image représentative du produit lui-même ?",
                },
            ],
        }],
        timeout=30.0,
    )

    raw  = clean_json_response(response.content[0].text)
    clf  = json.loads(raw)

    is_product = bool(clf.get("is_product_image", False))
    confidence = float(clf.get("confidence", 0.0))
    category   = clf.get("category", "other")
    reason     = clf.get("reason", "")
    accepted   = is_product and confidence >= CONFIDENCE_ACCEPT

    logging.info(
        "Classification → %s (confiance=%.2f, catégorie=%s) — %s",
        "accepted" if accepted else "rejected",
        confidence, category, reason
    )

    return Image(
        data_b64=data_b64,
        media_type=media_type,
        width=raw_image["width"],
        height=raw_image["height"],
        confidence=confidence,
        category=category,
        reason=reason,
        accepted=accepted,
    )
