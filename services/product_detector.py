"""
Détection des produits dans un PDF — traitement page par page en parallèle.
1 page = 1 requête Claude légère → scalable jusqu'à 100+ pages sans timeout.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic

from config import ANTHROPIC_MODEL
from prompts.detect_prompt import PROMPT_DETECT
from utils.json_helpers import clean_json_response

# Nombre max de pages analysées en parallèle
MAX_PAGE_WORKERS = 5


def detect_products_on_page(
    client:   anthropic.Anthropic,
    page:     dict,
) -> list[dict]:
    """
    Détecte les produits sur une seule page.
    Retourne : [{ nom, pages: [page_num] }]
    """
    response = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=PROMPT_DETECT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type":       "base64",
                        "media_type": page["media_type"],
                        "data":       page["data_b64"],
                    },
                },
                {
                    "type": "text",
                    "text": f"Identifie tous les produits présents sur cette page ({page['page_num']}).",
                },
            ],
        }],
        timeout=60.0,
    )

    raw    = clean_json_response(response.content[0].text)
    result = json.loads(raw)

    # Force le numéro de page correct
    produits = []
    for p in result.get("produits", []):
        produits.append({
            "nom":   p.get("nom", ""),
            "pages": [page["page_num"]],
        })

    logging.info(
        "Page %d → %d produit(s) détecté(s)",
        page["page_num"], len(produits)
    )
    return produits


def consolidate_products(all_detections: list[dict]) -> list[dict]:
    """
    Consolide les produits détectés sur plusieurs pages.
    Fusionne les entrées avec le même nom en regroupant leurs pages.
    Ex: [{ nom: "Gant", pages: [1] }, { nom: "Gant", pages: [2] }]
      → [{ nom: "Gant", pages: [1, 2] }]
    """
    consolidated = {}

    for detection in all_detections:
        nom = detection.get("nom", "").strip()
        if not nom:
            continue

        # Normalise le nom pour la comparaison (minuscules, sans espaces doubles)
        nom_key = " ".join(nom.lower().split())

        if nom_key in consolidated:
            # Ajoute les pages sans doublon
            existing_pages = set(consolidated[nom_key]["pages"])
            new_pages      = set(detection.get("pages", []))
            consolidated[nom_key]["pages"] = sorted(existing_pages | new_pages)
        else:
            consolidated[nom_key] = {
                "nom":   nom,
                "pages": detection.get("pages", []),
            }

    result = list(consolidated.values())
    logging.info("%d produit(s) après consolidation", len(result))
    return result


def detect_products(client: anthropic.Anthropic, pages: list[dict]) -> list[dict]:
    """
    Détecte tous les produits dans le PDF — page par page en parallèle.
    Scalable jusqu'à 100+ pages sans timeout.
    Retourne : [{ nom, pages[] }]
    """
    if not pages:
        return []

    all_detections = []

    with ThreadPoolExecutor(max_workers=MAX_PAGE_WORKERS) as executor:
        future_to_page = {
            executor.submit(detect_products_on_page, client, page): page
            for page in pages
        }

        for future in as_completed(future_to_page):
            page = future_to_page[future]
            try:
                detections = future.result()
                all_detections.extend(detections)
            except Exception as exc:
                logging.warning(
                    "Détection page %d échouée : %s",
                    page["page_num"], exc
                )

    # Consolide les produits détectés sur plusieurs pages
    return consolidate_products(all_detections)
