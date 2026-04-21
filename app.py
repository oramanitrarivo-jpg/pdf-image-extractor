"""
Webhook Flask — Extraction de produits depuis un PDF
Architecture asynchrone : POST lance le traitement, GET récupère le résultat.
"""

import logging
import os
import threading
import uuid

from flask import Flask, jsonify, request

from tasks import process_pdf

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# Stockage en mémoire des jobs — { job_id: { status, step, accepted, ... } }
JOB_STORE: dict = {}


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


# ─── Endpoint POST /extract-images ─────────────────────────────────────────────

@app.route("/extract-images", methods=["POST"])
def extract_images_route():
    """
    Reçoit le PDF et lance le traitement en arrière-plan.
    Retourne immédiatement un job_id sans attendre la fin du traitement.
    """
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"error": "Clé API Anthropic manquante."}), 500

        pdf_bytes, pdf_name = get_pdf_from_request()
        if not pdf_bytes:
            return jsonify({"error": "Envoie le PDF en multipart (champ file) ou en body PDF."}), 400

        max_pages = request.args.get("max_pages", type=int)
        job_id    = str(uuid.uuid4())

        # Initialise le job
        JOB_STORE[job_id] = {
            "status":   "queued",
            "step":     "en attente",
            "pdf_name": pdf_name,
        }

        # Lance le traitement dans un thread séparé
        thread = threading.Thread(
            target=process_pdf,
            kwargs={
                "job_store": JOB_STORE,
                "job_id":    job_id,
                "pdf_bytes": pdf_bytes,
                "pdf_name":  pdf_name,
                "api_key":   api_key,
                "max_pages": max_pages,
            },
            daemon=True,
        )
        thread.start()

        logging.info("Job %s lancé pour '%s'", job_id, pdf_name)

        return jsonify({
            "job_id": job_id,
            "status": "queued",
        }), 202

    except Exception as exc:
        logging.exception("Erreur inattendue")
        return jsonify({"error": str(exc)}), 500


# ─── Endpoint GET /status/<job_id> ─────────────────────────────────────────────

@app.route("/status/<job_id>", methods=["GET"])
def status_route(job_id: str):
    """
    Retourne le statut du job.
    - status: "queued"     → en attente
    - status: "processing" → en cours (step indique l'étape)
    - status: "done"       → terminé, accepted[] disponible
    - status: "error"      → erreur, error indique le message
    """
    job = JOB_STORE.get(job_id)

    if not job:
        return jsonify({"error": f"Job {job_id} introuvable."}), 404

    status = job.get("status")

    # Job en cours — retourne juste le statut et l'étape
    if status in ("queued", "processing"):
        return jsonify({
            "job_id": job_id,
            "status": status,
            "step":   job.get("step", ""),
        }), 200

    # Job terminé — retourne les résultats complets
    if status == "done":
        return jsonify({
            "job_id":          job_id,
            "status":          "done",
            "total_extracted": job.get("total_extracted", 0),
            "accepted":        job.get("accepted", []),
            "rejected":        job.get("rejected", []),
        }), 200

    # Job en erreur
    return jsonify({
        "job_id": job_id,
        "status": "error",
        "error":  job.get("error", "Erreur inconnue"),
    }), 500


# ─── Lancement ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
