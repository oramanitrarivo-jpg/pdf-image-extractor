import base64
import json
import logging
import os

import anthropic
import fitz
from flask import Flask, jsonify, request

CONFIDENCE_ACCEPT = 0.80
MIN_IMAGE_BYTES = 1500
MIN_IMAGE_DIMENSION = 75

SYSTEM_PROMPT = """
Tu es un expert en analyse d'images pour catalogues produits e-commerce.
Tu reçois des images extraites d'une fiche produit PDF.

Une image représentative du produit EST :
- Une photo réelle du produit physique (sur fond blanc, coloré, ou en situation)
- Un packshot (vue principale du produit seul)
- Une vue éclatée montrant les composants du produit
- Un rendu 3D photoréaliste du produit lui-même
- Une illustration technique fidèle de la forme du produit

Une image représentative du produit N'EST PAS :
- Un logo de marque, certification ou norme (ISO, CE, NF, etc.)
- Une icône, pictogramme ou symbole graphique
- Un fond uni, dégradé ou texture décorative
- Une bannière, séparateur ou élément graphique de mise en page
- Un QR code ou code-barres
- Un tableau de données, grille de dimensions ou guide de tailles
  (ex: tableau diamètre intérieur / extérieur, grille de coloris, tableau de compatibilité)
- Un schéma d'installation ou diagramme technique sans le produit visible
- Une infographie ou badge promotionnel (ex: "Garantie 5 ans", "Économie d'énergie")
- Une capture d'écran d'interface ou d'application

RÈGLE CRITIQUE : Si l'image contient principalement du texte, des cases, des colonnes
ou des lignes de données — même si elle est liée au produit — ce n'est PAS une image produit.

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "is_product_image": boolean,
  "confidence": float entre 0.0 et 1.0,
  "category": "product_photo" | "logo" | "icon" | "decoration" | "size_chart" | "diagram" | "badge" | "other",
  "reason": "une phrase courte expliquant ta décision, sans mentionner le nom ou la marque du produit"
}
""".strip()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

EXT_MAP = {"png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp"}


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
                size = len(base_image["image"])
                w, h = base_image["width"], base_image["height"]
                # LOG TEMPORAIRE
                logging.info("Image xref=%d : taille=%d octets, dimensions=%dx%d", xref, size, w, h)
                if size < MIN_IMAGE_BYTES:
                    continue
                if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                    continue
                images.append(base_image)
            except Exception as e:
                logging.warning("Erreur extraction xref=%d : %s", xref, e)
    doc.close()
    return images


def classify(client, img):
    media_type = EXT_MAP.get(img["ext"].lower(), "image/png")
    data_b64 = base64.standard_b64encode(img["image"]).decode()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data_b64}
                },
                {
                    "type": "text",
                    "text": "Est-ce une image représentative du produit lui-même ?"
                }
            ]
        }],
        timeout=30.0
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
        accepted = []
        rejected = []

        for idx, img in enumerate(raw_images):
            try:
                clf = classify(client, img)
            except Exception as e:
                logging.warning("Classification image %d échouée : %s", idx, e)
                rejected.append({"index": idx, "category": "error", "reason": str(e)})
                continue

            is_product = bool(clf.get("is_product_image", False))
            confidence = float(clf.get("confidence", 0.0))
            category = clf.get("category", "other")
            reason = clf.get("reason", "")
            accepted_image = is_product and confidence >= CONFIDENCE_ACCEPT

            logging.info(
                "Image %d → %s (confiance=%.2f, catégorie=%s) — %s",
                idx, "accepted" if accepted_image else "rejected",
                confidence, category, reason
            )

            record = {
                "index": idx,
                "confidence": confidence,
                "category": category,
                "reason": reason,
                "width": img["width"],
                "height": img["height"],
            }

            if accepted_image:
                record["data_b64"] = base64.standard_b64encode(img["image"]).decode()
                record["media_type"] = EXT_MAP.get(img["ext"].lower(), "image/png")
                accepted.append(record)
            else:
                rejected.append(record)

        return jsonify({
            "total_extracted": len(raw_images),
            "accepted": accepted,
            "rejected": rejected,
        }), 200

    except Exception as e:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
