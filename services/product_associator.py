import json
import logging

import anthropic

from config import ANTHROPIC_MODEL
from models.image import Image
from models.product import Product
from prompts.associate_prompt import PROMPT_ASSOCIATE
from utils.json_helpers import clean_json_response


def build_content(pages: list[dict], accepted_images: list[Image]) -> list[dict]:
    """
    Construit le contenu pour Claude :
    pages rendues + images acceptées + texte de demande.
    """
    content = []

    # Pages rendues pour la mise en page
    for p in pages:
        content.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": p["media_type"],
                "data":       p["data_b64"],
            },
        })

    # Images déjà acceptées par le classifier
    for img in accepted_images:
        content.append({
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": img.media_type,
                "data":       img.data_b64,
            },
        })

    return content


def associate_images(
    client:          anthropic.Anthropic,
    nom_produit:     str,
    pages:           list[dict],
    accepted_images: list[Image],
    source_pdf:      str,
    date_ajout:      str,
) -> Product:
    """
    Passe 2 — Associe les images acceptées à un produit spécifique
    et extrait ses informations structurées.
    Retourne un Product complet.
    """
    content = build_content(pages, accepted_images)
    content.append({
        "type": "text",
        "text": (
            f"Extrait les informations du produit '{nom_produit}'.\n"
            f"Les images acceptées sont indexées de 0 à {len(accepted_images) - 1}.\n"
            f"Associe uniquement les images qui représentent CE produit spécifique."
        ),
    })

    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=PROMPT_ASSOCIATE.format(nom_produit=nom_produit),
        messages=[{"role": "user", "content": content}],
        timeout=60.0,
    )

    raw     = clean_json_response(response.content[0].text)
    details = json.loads(raw)

    # Association des images par indices
    images_indices = details.get("images_indices", [])
    images_produit = []
    for idx in images_indices:
        if 0 <= idx < len(accepted_images):
            images_produit.append(accepted_images[idx])

    logging.info(
        "Produit '%s' — %d image(s) associée(s)",
        nom_produit, len(images_produit)
    )

    return Product(
        nom=details.get("nom", nom_produit),
        descriptif=details.get("descriptif", ""),
        caracteristiques=details.get("caracteristiques", ""),
        images=images_produit,
        source_pdf=source_pdf,
        date_ajout=date_ajout,
    )
