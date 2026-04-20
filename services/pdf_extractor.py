import base64
import logging

import fitz

from config import EXT_MAP, MIN_IMAGE_BYTES, MIN_IMAGE_DIMENSION, PAGE_RENDER_DPI


def extract_images(pdf_bytes: bytes, max_pages: int = None) -> list[dict]:
    """
    Extrait les images embarquées haute résolution depuis le PDF.
    max_pages : limite le nombre de pages à lire (None = toutes les pages)
    Retourne : [{ image, ext, width, height }]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    seen = set()

    pages = list(doc)
    if max_pages:
        pages = pages[:max_pages]
        logging.info("Mode test : lecture limitée aux %d première(s) page(s)", max_pages)

    for page in pages:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            if xref in seen:
                continue
            seen.add(xref)
            try:
                base_image = doc.extract_image(xref)
                size = len(base_image["image"])
                w, h = base_image["width"], base_image["height"]

                logging.info(
                    "Image xref=%d : taille=%d octets, dimensions=%dx%d",
                    xref, size, w, h
                )

                if size < MIN_IMAGE_BYTES:
                    logging.debug("Image xref=%d ignorée (taille=%d)", xref, size)
                    continue
                if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                    logging.debug("Image xref=%d ignorée (dimensions=%dx%d)", xref, w, h)
                    continue

                images.append(base_image)

            except Exception as exc:
                logging.warning("Erreur extraction xref=%d : %s", xref, exc)

    doc.close()
    logging.info("%d image(s) embarquée(s) extraite(s)", len(images))
    return images


def render_pages_as_images(pdf_bytes: bytes, max_pages: int = None) -> list[dict]:
    """
    Convertit chaque page du PDF en image PNG base64.
    max_pages : limite le nombre de pages à rendre (None = toutes les pages)
    Retourne : [{ page_num, data_b64, media_type }]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    mat = fitz.Matrix(PAGE_RENDER_DPI / 72, PAGE_RENDER_DPI / 72)

    total = len(doc)
    limit = min(max_pages, total) if max_pages else total

    for i in range(limit):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat)
        data_b64 = base64.standard_b64encode(pix.tobytes("png")).decode()
        pages.append({
            "page_num":   i + 1,
            "data_b64":   data_b64,
            "media_type": "image/png",
        })

    doc.close()
    logging.info("%d page(s) rendue(s) depuis le PDF", len(pages))
    return pages
