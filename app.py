import base64
import json
import logging
import os

import anthropic
import fitz
from flask import Flask, jsonify, request

CONFIDENCE_ACCEPT = 0.75
CONFIDENCE_REVIEW = 0.50
MIN_IMAGE_BYTES = 5000

SYSTEM_PROMPT = """
Tu es un expert en analyse d'images pour catalogues produits e-commerce.
Extraire les images dans un fichier PDF.

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "is_product_image": boolean,
  "confidence": float entre 0.0 et 1.0,
  "category": "product_photo" | "logo" | "icon" | "decoration" | "other",
  "reason": "une phrase courte expliquant la décision, sans mentionner d’informations spécifiques au produit (nom, description, marque, etc.)"
}

Règles :
- "is_product_image" :
  - Déterminé PRIORITAIREMENT en se basant sur la liste de critères fournie (issue des tests).
  - Cette liste sert de référence principale pour la décision.
  - Comparer l’image aux critères et évaluer leur correspondance.
  - true si l’image correspond clairement aux critères définissant une image produit.
  - false si elle ne correspond pas ou correspond davantage à une autre catégorie (logo, icône, décoration, etc.).
  - En cas d’ambiguïté, se baser sur le nombre et la pertinence des critères correspondants.
  - Ne pas se fier à une intuition globale : la décision doit être justifiée par les critères de la liste.
- "confidence" = niveau de certitude de la classification.
- "category" :
  - product_photo : image principale d’un produit
  - logo : logo de marque ou d’entreprise
  - icon : pictogramme ou élément graphique simple
  - decoration : image d’ambiance, bannière ou fond visuel
  - other : tout autre cas
- "reason" doit être générique et basée uniquement sur des indices visuels (ex: fond blanc, objet centré, style graphique, etc.).
- Ne jamais inclure d’informations spécifiques extraites ou supposées du produit.

Est une image produit : 
- photo du produit, 
- packshot, 
- vue éclatée, 
- rendu 3D.
- présentation catalogue

N'est PAS une image produit : 
- logo, 
- icône, 
- fond,
- bannière, 
- QR code, 
- texture.
- Petite image sombre sans objet identifiable, fond texturé.
- Bande verticale très étroite, élément graphique décoratif.
- Logotype typographique avec symbole graphique sur fond blanc.
- Élément graphique de tableau avec bandes alternées et en-têtes textuels.
- Étiquette texte sur fond sombre, élément d'interface documentaire.
- Pictogramme monochrome simplifié sur fond uni, style icône.
- Titre typographique large sur fond sombre, élément de mise en page.
""".strip()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


def extract_images(pdf_bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    seen = set()
    for page in doc:
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base_image = doc.extract_image(xref)
                if len(base_image["image"]) >= MIN_IMAGE_BYTES:
                    images.append(base_image)
            except Exception as e:
                logging.warning("Erreur extraction xref=%d : %s", xref, e)
    doc.close()
    return images


def classify(client, img):
    ext_map = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}
    media_type = ext_map.get(img["ext"].lower(), "image/png")
    data_b64 = base64.standard_b64encode(img["image"]).decode()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_b64}},
                {"type": "text", "text": "Est-ce une image représentative du produit ?"}
            ]
        }]
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


@app.route("/extract-images", methods=["POST"])
def extract_images_route():
    try:
        # Lecture de la clé à chaque requête
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        if "file" in request.files:
            pdf_bytes = request.files["file"].read()
        elif request.content_type and "pdf" in request.content_type:
            pdf_bytes = request.data
        else:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        if not pdf_bytes:
            return jsonify({"error": "Fichier PDF vide."}), 400

        try:
            raw_images = extract_images(pdf_bytes)
        except Exception as e:
            return jsonify({"error": f"Extraction échouée : {str(e)}"}), 500

        client = anthropic.Anthropic(api_key=api_key)
        accepted, review, rejected = [], [], []

        for idx, img in enumerate(raw_images):
            try:
                clf = classify(client, img)
            except Exception as e:
                rejected.append({"index": idx, "reason": str(e)})
                continue

            is_product = bool(clf.get("is_product_image", False))
            confidence = float(clf.get("confidence", 0.0))
            status = "accepted" if is_product and confidence >= CONFIDENCE_ACCEPT else \
                     "review" if is_product and confidence >= CONFIDENCE_REVIEW else "rejected"

            ext_map = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}
            record = {
                "index": idx,
                "confidence": confidence,
                "category": clf.get("category", "other"),
                "reason": clf.get("reason", ""),
                "width": img["width"],
                "height": img["height"],
            }
            if status in ("accepted", "review"):
                record["data_b64"] = base64.standard_b64encode(img["image"]).decode()
                record["media_type"] = ext_map.get(img["ext"].lower(), "image/png")

            if status == "accepted":
                accepted.append(record)
            elif status == "review":
                review.append(record)
            else:
                rejected.append(record)

        return jsonify({
            "total_extracted": len(raw_images),
            "accepted": accepted,
            "review": review,
            "rejected": rejected,
        }), 200

    except Exception as e:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
