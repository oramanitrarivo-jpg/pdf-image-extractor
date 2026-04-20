import base64
import hashlib
import json
import logging
import os
import re

import anthropic
import fitz
from flask import Flask, jsonify, request

# ─────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────
CONFIDENCE_ACCEPT = 0.85
CONFIDENCE_REVIEW = 0.65
MIN_IMAGE_BYTES   = 5_000   # poids brut minimum
MIN_IMAGE_PX      = 150     # plus grand côté minimum en pixels

MEDIA_TYPE_MAP = {
    "png":  "image/png",
    "jpeg": "image/jpeg",
    "jpg":  "image/jpeg",
    "webp": "image/webp",
}

SYSTEM_PROMPT = """
Tu es un classificateur d'images pour catalogues produits e-commerce.
Ta seule tâche est de déterminer si une image extraite d'un PDF est une photo produit ou non.

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "is_product_image": boolean,
  "confidence": float entre 0.0 et 1.0,
  "category": "product_photo" | "logo" | "icon" | "decoration" | "other",
  "reason": "une phrase courte basée uniquement sur des indices visuels génériques"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RÈGLE PRINCIPALE — is_product_image
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Par défaut, is_product_image = false.
Ne passer à true QUE si l'image correspond CLAIREMENT à un critère positif
ET n'est pas disqualifiée par un critère négatif.

EST une image produit (true) :
- Photo réaliste d'un objet physique isolé sur fond neutre (blanc, noir, gris)
- Packshot : objet centré, éclairage produit, rendu commercial
- Vue éclatée ou schéma technique d'un objet physique
- Rendu 3D photoréaliste d'un produit
→ L'objet doit être CLAIREMENT IDENTIFIABLE et PRINCIPAL dans l'image.

N'EST PAS une image produit (false) — disqualifié si :
- Contient principalement du texte (titre, étiquette, en-tête de tableau)
- Logo ou logotype (même partiel) : symbole + texte de marque
- Pictogramme ou icône monochrome simplifiée
- Fond uni ou texturé sans objet identifiable
- Bande, bordure ou élément décoratif de mise en page
- Bannière, image d'ambiance ou fond de page
- Image floue, sombre ou illisible sans objet reconnaissable
- Élément graphique de tableau (lignes, colonnes, en-têtes visuels)

━━━━━━━━━━━━━━━━━━━━━━━━━━
RÈGLES COMPLÉMENTAIRES
━━━━━━━━━━━━━━━━━━━━━━━━━━
- Si l'image contient à la fois un produit ET un logo/texte superposé,
  évaluer ce qui est DOMINANT visuellement.
- En cas de doute : is_product_image = false, confidence < 0.6.
- "reason" : indices visuels uniquement, jamais de nom de marque ou de produit.
""".strip()


# ─────────────────────────────────────────────
# Application Flask
# ─────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ─────────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────────
def extract_images(pdf_bytes: bytes) -> list[dict]:
    """
    Extrait les images du PDF en filtrant :
    - les doublons (xref + hash MD5 du contenu)
    - les images trop petites (poids < MIN_IMAGE_BYTES ou dimensions < MIN_IMAGE_PX)
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images      = []
    seen_xrefs  = set()
    seen_hashes = set()

    for page in doc:
        for img in page.get_images(full=True):
            xref = img[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)

            try:
                base_image = doc.extract_image(xref)
            except Exception as e:
                logging.warning("Extraction échouée xref=%d : %s", xref, e)
                continue

            img_bytes = base_image["image"]

            # Filtre poids
            if len(img_bytes) < MIN_IMAGE_BYTES:
                logging.info("Ignoré xref=%d : trop léger (%d octets)", xref, len(img_bytes))
                continue

            # Filtre dimensions
            w, h = base_image.get("width", 0), base_image.get("height", 0)
            if max(w, h) < MIN_IMAGE_PX:
                logging.info("Ignoré xref=%d : trop petit (%dx%d px)", xref, w, h)
                continue

            # Filtre doublon contenu
            content_hash = hashlib.md5(img_bytes).hexdigest()
            if content_hash in seen_hashes:
                logging.info("Ignoré xref=%d : doublon (hash=%s)", xref, content_hash)
                continue
            seen_hashes.add(content_hash)

            images.append(base_image)

    doc.close()
    logging.info("Extraction : %d image(s) retenue(s)", len(images))
    return images


# ─────────────────────────────────────────────
# Classification
# ─────────────────────────────────────────────
def parse_llm_json(raw: str) -> dict:
    """Nettoie la réponse LLM et parse le JSON de façon robuste."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())
    return json.loads(cleaned)


def classify(client: anthropic.Anthropic, img: dict) -> dict:
    """Appelle Claude pour classifier une image."""
    media_type = MEDIA_TYPE_MAP.get(img["ext"].lower(), "image/png")
    data_b64   = base64.standard_b64encode(img["image"]).decode()
    w, h       = img.get("width", 0), img.get("height", 0)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=256,
        system=SYSTEM_PROMPT,
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
                    # Formulation neutre + dimensions pour renforcer la règle MIN_IMAGE_PX
                    "text": f"Classifie cette image. Dimensions : {w}x{h}px.",
                },
            ],
        }],
    )

    raw = response.content[0].text.strip()
    return parse_llm_json(raw)


def resolve_status(is_product: bool, confidence: float) -> str:
    """Détermine le statut final de façon explicite et lisible."""
    if not is_product:
        return "rejected"
    if confidence >= CONFIDENCE_ACCEPT:
        return "accepted"
    if confidence >= CONFIDENCE_REVIEW:
        return "review"
    return "rejected"


# ─────────────────────────────────────────────
# Route principale
# ─────────────────────────────────────────────
@app.route("/extract-images", methods=["POST"])
def extract_images_route():
    try:
        # Clé API
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        # Lecture du PDF
        if "file" in request.files:
            pdf_bytes = request.files["file"].read()
        elif request.content_type and "pdf" in request.content_type:
            pdf_bytes = request.data
        else:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        if not pdf_bytes:
            return jsonify({"error": "Fichier PDF vide."}), 400

        # Extraction
        try:
            raw_images = extract_images(pdf_bytes)
        except Exception as e:
            return jsonify({"error": f"Extraction échouée : {e}"}), 500

        # Classification
        client = anthropic.Anthropic(api_key=api_key)
        accepted, review, rejected = [], [], []

        for idx, img in enumerate(raw_images):
            try:
                clf = classify(client, img)
            except Exception as e:
                logging.error("Erreur classification img[%d] : %s", idx, e)
                rejected.append({"index": idx, "reason": str(e)})
                continue

            is_product = bool(clf.get("is_product_image", False))
            confidence = float(clf.get("confidence", 0.0))
            status     = resolve_status(is_product, confidence)

            logging.info(
                "img[%d] %dx%d → %s | is_product=%s | conf=%.2f | %s",
                idx,
                img.get("width", 0),
                img.get("height", 0),
                clf.get("category", "?"),
                is_product,
                confidence,
                clf.get("reason", ""),
            )

            record = {
                "index":      idx,
                "confidence": confidence,
                "category":   clf.get("category", "other"),
                "reason":     clf.get("reason", ""),
                "width":      img.get("width", 0),
                "height":     img.get("height", 0),
            }

            if status in ("accepted", "review"):
                record["data_b64"]   = base64.standard_b64encode(img["image"]).decode()
                record["media_type"] = MEDIA_TYPE_MAP.get(img["ext"].lower(), "image/png")

            if status == "accepted":
                accepted.append(record)
            elif status == "review":
                review.append(record)
            else:
                rejected.append(record)

        return jsonify({
            "total_extracted": len(raw_images),
            "accepted":        accepted,
            "review":          review,
            "rejected":        rejected,
        }), 200

    except Exception:
        logging.exception("Erreur inattendue")
        return jsonify({"error": "Erreur interne du serveur."}), 500


# ─────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
