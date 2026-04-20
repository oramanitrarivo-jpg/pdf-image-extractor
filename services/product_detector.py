import json
import logging
import anthropic
from config import ANTHROPIC_MODEL
from prompts.detect_prompt import PROMPT_DETECT
from utils.json_helpers import clean_json_response

def build_pages_content(pages: list[dict]) -> list[dict]:
    """Construit la liste de blocs image pour l'API Claude."""
    return [
        {
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": p["media_type"],
                "data":       p["data_b64"],
            },
        }
        for p in pages
    ]


def detect_products(client: anthropic.Anthropic, pages: list[dict]) -> list[dict]:
    """
    Passe 1 — Détecte tous les produits et leurs pages dans le PDF.
    Retourne : [{ nom, pages[] }]
    """
    content = build_pages_content(pages)
    content.append({
        "type": "text",
        "text": "Identifie tous les produits présents dans ces pages de catalogue.",
    })

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=PROMPT_DETECT,
        messages=[{"role": "user", "content": content}],
        timeout=60.0,
    )

    raw      = clean_json_response(response.content[0].text)
    result   = json.loads(raw)
    produits = result.get("produits", [])

    logging.info("%d produit(s) détecté(s)", len(produits))
    return produits
