"""
Webhook Flask — Extraction de produits depuis un PDF
"""

import logging
import os
from datetime import date

import anthropic
from flask import Flask, jsonify, request

from config import ANTHROPIC_API_KEY
from models.image import Image
from services.image_classifier import classify
from services.pdf_extractor import extract_images, render_pages_as_images
from services.product_associator import associate_images
from services.product_detector import detect_products

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


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


# ─── Endpoint extract-images (inchangé) ───────────────────────────────────────

@app.route("/extract-images", methods=["POST"])
def extract_images_route():
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        pdf_bytes, _ = get_pdf_from_request()
        if not pdf_bytes:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        raw_images = extract_images(pdf_bytes)
        client     = anthropic.Anthropic(api_key=api_key)
        accepted   = []
        rejected   = []

        for raw_img in raw_images:
            try:
                img = classify(client, raw_img)
            except Exception as exc:
                logging.warning("Classification échouée : %s", exc)
                rejected.append({"category": "error", "reason": str(exc)})
                continue

            if img.accepted:
                accepted.append(img.to_dict())
            else:
                rejected.append({
                    "confidence": img.confidence,
                    "category":   img.category,
                    "reason":     img.reason,
                    "width":      img.width,
                    "height":     img.height,
                })

        return jsonify({
            "total_extracted": len(raw_images),
            "accepted":        accepted,
            "rejected":        rejected,
        }), 200

    except Exception as exc:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(exc)}), 500


# ─── Endpoint extract-products (nouveau) ──────────────────────────────────────

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

        # 1. Extraction des images embarquées
        raw_images = extract_images(pdf_bytes)

        # 2. Classification de toutes les images — système éprouvé inchangé
        accepted_images = []
        for raw_img in raw_images:
            try:
                img = classify(client, raw_img)
                if img.accepted:
                    accepted_images.append(img)
            except Exception as exc:
                logging.warning("Classification échouée : %s", exc)

        logging.info("%d image(s) acceptée(s) sur %d", len(accepted_images), len(raw_images))

        # 3. Rendu des pages pour analyse de la mise en page
        all_pages = render_pages_as_images(pdf_bytes)

        # 4. Détection des produits — Passe 1
        try:
            detected = detect_products(client, all_pages)
        except Exception as exc:
            return jsonify({"error": f"Détection des produits échouée : {exc}"}), 500

        if not detected:
            return jsonify({"total_produits": 0, "produits": []}), 200

        # 5. Association images ↔ produits — Passe 2
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
