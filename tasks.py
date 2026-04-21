"""
Traitement asynchrone des PDFs en arrière-plan.
Utilise les threads Python natifs — pas de Redis ni de Celery requis.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import anthropic

from services.image_classifier import classify
from services.pdf_extractor import extract_images, render_pages_as_images
from services.product_associator import associate_images
from services.product_detector import detect_products

# Nombre max de classifications en parallèle
MAX_WORKERS = 5


# ─── Utilitaires ───────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    """
    Convertit un nom produit en nom de fichier propre.
    Ex: "AIR/WATER 20 BAR" → "AIR-WATER-20-BAR"
    """
    name = name.strip()
    name = re.sub(r"[^\w\s-]", "-", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def generate_filenames(product_name: str, count: int, media_type: str) -> list[str]:
    """
    Génère les noms de fichiers pour un produit.
    - 1 image  → "gant.jpg"
    - N images → "gant_1.jpg", "gant_2.jpg", ...
    """
    ext  = "jpg" if "jpeg" in media_type or "jpg" in media_type else "png"
    slug = slugify(product_name)

    if count == 1:
        return [f"{slug}.{ext}"]
    return [f"{slug}_{i + 1}.{ext}" for i in range(count)]


def get_pages_for_product(all_pages: list[dict], page_numbers: list[int]) -> list[dict]:
    """Filtre les pages selon les numéros indiqués par Claude."""
    page_set = set(page_numbers)
    filtered = [p for p in all_pages if p["page_num"] in page_set]
    return filtered or all_pages


def classify_all_parallel(client: anthropic.Anthropic, raw_images: list[dict]) -> tuple:
    """
    Classifie toutes les images en parallèle.
    Retourne : (accepted_images, rejected)
    """
    accepted_images = []
    rejected        = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_idx = {
            executor.submit(classify, client, img): idx
            for idx, img in enumerate(raw_images)
        }

        results = {}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                logging.warning("Classification image %d échouée : %s", idx, exc)
                results[idx] = None

    for idx in sorted(results.keys()):
        img = results[idx]
        if img is None:
            rejected.append({"category": "error", "reason": "classification échouée"})
        elif img.accepted:
            accepted_images.append(img)
        else:
            rejected.append({
                "confidence": img.confidence,
                "category":   img.category,
                "reason":     img.reason,
            })

    logging.info(
        "%d image(s) acceptée(s) sur %d",
        len(accepted_images), len(raw_images)
    )
    return accepted_images, rejected


# ─── Traitement principal ───────────────────────────────────────────────────────

def process_pdf(
    job_store:     dict,
    job_id:        str,
    pdf_bytes:     bytes,
    pdf_name:      str,
    api_key:       str,
    max_pages:     int = None,
) -> None:
    """
    Traitement complet du PDF en arrière-plan.
    Met à jour job_store[job_id] au fur et à mesure.
    """
    try:
        job_store[job_id]["status"] = "processing"
        pdf_name_clean = pdf_name.replace(".pdf", "").replace(".PDF", "")
        client         = anthropic.Anthropic(api_key=api_key)

        # 1. Extraction des images embarquées
        job_store[job_id]["step"] = "extraction des images"
        raw_images = extract_images(pdf_bytes, max_pages)

        # 2. Classification parallèle
        job_store[job_id]["step"] = "classification des images"
        accepted_images, rejected = classify_all_parallel(client, raw_images)

        # 3. Rendu des pages
        job_store[job_id]["step"] = "analyse des pages"
        all_pages = render_pages_as_images(pdf_bytes, max_pages)

        # 4. Détection des produits page par page en parallèle
        job_store[job_id]["step"] = "détection des produits"
        detected = detect_products(client, all_pages)

        # 5. Association images ↔ produits
        job_store[job_id]["step"] = "association images ↔ produits"
        accepted_out = []

        if detected:
            for produit_info in detected:
                nom       = produit_info.get("nom", "")
                page_nums = produit_info.get("pages", [])

                if not nom:
                    continue

                pages_produit = get_pages_for_product(all_pages, page_nums)

                try:
                    product = associate_images(
                        client=client,
                        nom_produit=nom,
                        pages=pages_produit,
                        accepted_images=accepted_images,
                        source_pdf=pdf_name_clean,
                        date_ajout=date.today().isoformat(),
                    )
                except Exception as exc:
                    logging.warning("Association '%s' échouée : %s", nom, exc)
                    continue

                if not product.images:
                    logging.info("Produit '%s' — aucune image associée", nom)
                    continue

                filenames = generate_filenames(
                    product.nom,
                    len(product.images),
                    product.images[0].media_type,
                )

                for img, filename in zip(product.images, filenames):
                    accepted_out.append({
                        "data_b64":     img.data_b64,
                        "media_type":   img.media_type,
                        "width":        img.width,
                        "height":       img.height,
                        "confidence":   img.confidence,
                        "product_name": product.nom,
                        "filename":     filename,
                    })

        else:
            # Fallback — pas de produit détecté, on utilise le nom du PDF
            filenames = generate_filenames(
                pdf_name_clean,
                len(accepted_images),
                accepted_images[0].media_type if accepted_images else "image/jpeg",
            )
            for img, filename in zip(accepted_images, filenames):
                accepted_out.append({
                    "data_b64":     img.data_b64,
                    "media_type":   img.media_type,
                    "width":        img.width,
                    "height":       img.height,
                    "confidence":   img.confidence,
                    "product_name": pdf_name_clean,
                    "filename":     filename,
                })

        # 6. Mise à jour du job avec les résultats
        job_store[job_id].update({
            "status":          "done",
            "step":            "terminé",
            "total_extracted": len(raw_images),
            "accepted":        accepted_out,
            "rejected":        rejected,
        })

        logging.info(
            "Job %s terminé — %d image(s) acceptée(s)",
            job_id, len(accepted_out)
        )

    except Exception as exc:
        logging.exception("Job %s échoué : %s", job_id, exc)
        job_store[job_id].update({
            "status": "error",
            "error":  str(exc),
        })
