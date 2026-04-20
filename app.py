"""
Webhook Flask — Extraction de produits depuis un PDF
"""

import logging
import os
import re
from datetime import date

import anthropic
from flask import Flask, jsonify, request

from services.image_classifier import classify
from services.pdf_extractor import extract_images, render_pages_as_images
from services.product_associator import associate_images
from services.product_detector import detect_products

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ─── Utilitaires ───────────────────────────────────────────────────────────────

def get_pdf_from_request() -> tuple[bytes, str]:
    """
    Récupère le PDF depuis la requête multipart ou body binaire.
    Retourne : (pdf_bytes, pdf_name)
    """
    if "file" in request.files:
        f = request.files["file"]
        return f.read(), f.filename or "document.pdf"
    if request.content_type and "pdf" in request.content_type:
        return request.data, request.headers.get("X-Filename", "document.pdf")
    return b"", ""


def get_pages_for_product(all_pages: list[dict], page_numbers: list[int]) -> list[dict]:
    """Filtre les pages selon les numéros indiqués par Claude."""
    page_set = set(page_numbers)
    filtered = [p for p in all_pages if p["page_num"] in page_set]
    return filtered or all_pages


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


# ─── Endpoint extract-images ───────────────────────────────────────────────────

@app.route("/extract-images", methods=["POST"])
def extract_images_route():
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        pdf_bytes, pdf_name = get_pdf_from_request()
        if not pdf_bytes:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        pdf_name_clean = pdf_name.replace(".pdf", "").replace(".PDF", "")
        client         = anthropic.Anthropic(api_key=api_key)

        # 1. Extraction des images embarquées
        raw_images = extract_images(pdf_bytes)

        # 2. Classification — système éprouvé inchangé
        accepted_images = []
        rejected        = []

        for raw_img in raw_images:
            try:
                img = classify(client, raw_img)
                if img.accepted:
                    accepted_images.append(img)
                else:
                    rejected.append({
                        "confidence": img.confidence,
                        "category":   img.category,
                        "reason":     img.reason,
                    })
            except Exception as exc:
                logging.warning("Classification échouée : %s", exc)
                rejected.append({"category": "error", "reason": str(exc)})

        logging.info(
            "%d image(s) acceptée(s) sur %d",
            len(accepted_images), len(raw_images)
        )

        # 3. Rendu des pages pour détecter les produits
        all_pages = render_pages_as_images(pdf_bytes)

        # 4. Détection des produits
        try:
            detected = detect_products(client, all_pages)
        except Exception as exc:
            logging.warning("Détection produits échouée, fallback pdf_name : %s", exc)
            detected = []

        # 5. Association images ↔ produits + génération des noms de fichiers
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

        return jsonify({
            "total_extracted": len(raw_images),
            "accepted":        accepted_out,
            "rejected":        rejected,
        }), 200

    except Exception as exc:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(exc)}), 500


# ─── Endpoint extract-products ─────────────────────────────────────────────────

@app.route("/extract-products", methods=["POST"])
def extract_products_route():
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        pdf_bytes, pdf_name = get_pdf_from_request()
        if not pdf_bytes:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        pdf_name_clean = pdf_name.replace(".pdf", "").replace(".PDF", "")
        today          = date.today().isoformat()
        client         = anthropic.Anthropic(api_key=api_key)

        # 1. Extraction et classification des images
        max_pages  = request.args.get("max_pages", type=int)
        raw_images = extract_images(pdf_bytes, max_pages)
        accepted_images = []

        for raw_img in raw_images:
            try:
                img = classify(client, raw_img)
                if img.accepted:
                    accepted_images.append(img)
            except Exception as exc:
                logging.warning("Classification échouée : %s", exc)

        logging.info(
            "%d image(s) acceptée(s) sur %d",
            len(accepted_images), len(raw_images)
        )

        # 2. Rendu des pages
        all_pages = render_pages_as_images(pdf_bytes, max_pages)

        # 3. Détection des produits
        try:
            detected = detect_products(client, all_pages)
        except Exception as exc:
            return jsonify({"error": f"Détection des produits échouée : {exc}"}), 500

        if not detected:
            return jsonify({"total_produits": 0, "produits": []}), 200

        # 4. Association images ↔ produits
        produits_out = []
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
                    date_ajout=today,
                )
                produits_out.append(product.to_dict())
            except Exception as exc:
                logging.warning("Association '%s' échouée : %s", nom, exc)

        return jsonify({
            "total_produits": len(produits_out),
            "produits":       produits_out,
        }), 200

    except Exception as exc:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(exc)}), 500


# ─── Lancement ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
