import io
import json
import logging
import base64

import anthropic

from config import ANTHROPIC_MODEL, CONFIDENCE_ACCEPT, EXT_MAP
from models.image import Image
from prompts.classify_prompt import PROMPT_CLASSIFY
from utils.json_helpers import clean_json_response

# Limite Claude API : 5 Mo — on envoie à 4.5 Mo max pour avoir de la marge
MAX_CLASSIFY_BYTES = 4_500_000


def resize_if_needed(image_bytes: bytes, media_type: str) -> bytes:
    """
    Réduit la taille de l'image si elle dépasse MAX_CLASSIFY_BYTES.
    Retourne l'image originale si elle est dans les limites.
    L'image originale n'est JAMAIS modifiée — on travaille sur une copie.
    """
    if len(image_bytes) <= MAX_CLASSIFY_BYTES:
        return image_bytes

    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(image_bytes))
        fmt = "JPEG" if "jpeg" in media_type or "jpg" in media_type else "PNG"

        # Réduit progressivement la qualité jusqu'à passer sous la limite
        quality = 85
        while quality >= 20:
            buffer = io.BytesIO()
            img.save(buffer, format=fmt, quality=quality, optimize=True)
            result = buffer.getvalue()

            if len(result) <= MAX_CLASSIFY_BYTES:
                logging.info(
                    "Image redimensionnée pour Claude : %d Mo → %d Mo (qualité=%d)",
                    len(image_bytes) // 1_000_000,
                    len(result) // 1_000_000,
                    quality,
                )
                return result
            quality -= 10

        # Si la qualité seule ne suffit pas, réduit aussi les dimensions
        w, h = img.size
        scale = 0.75
        while scale >= 0.25:
            new_w, new_h = int(w * scale), int(h * scale)
            resized = img.resize((new_w, new_h), PILImage.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format=fmt, quality=70, optimize=True)
            result = buffer.getvalue()

            if len(result) <= MAX_CLASSIFY_BYTES:
                logging.info(
                    "Image redimensionnée pour Claude : %dx%d → %dx%d",
                    w, h, new_w, new_h
                )
                return result
            scale -= 0.25

        logging.warning(
            "Impossible de réduire l'image sous %d Mo — envoi de l'original",
            MAX_CLASSIFY_BYTES // 1_000_000
        )
        return image_bytes

    except Exception as exc:
        logging.warning("Erreur redimensionnement : %s — envoi de l'original", exc)
        return image_bytes


def classify(client: anthropic.Anthropic, raw_image: dict) -> Image:
    """
    Classifie une image extraite du PDF via Claude Vision.
    - Envoie une copie compressée à Claude si l'image est trop grande
    - Conserve toujours l'image originale haute résolution pour Drive
    Retourne une Image enrichie avec confidence, category, reason et accepted.
    """
    media_type    = EXT_MAP.get(raw_image["ext"].lower(), "image/png")
    original_data = raw_image["image"]

    # Copie compressée pour Claude — l'original n'est jamais modifié
    classify_data = resize_if_needed(original_data, media_type)
    classify_b64  = base64.standard_b64encode(classify_data).decode()

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
                        "data":       classify_b64,
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

    # On stocke l'original haute résolution — pas la copie compressée
    original_b64 = base64.standard_b64encode(original_data).decode()

    return Image(
        data_b64=original_b64,
        media_type=media_type,
        width=raw_image["width"],
        height=raw_image["height"],
        confidence=confidence,
        category=category,
        reason=reason,
        accepted=accepted,
    )
