import re

def clean_json_response(text: str) -> str:
    """
    Nettoie la réponse de Claude pour extraire un JSON valide.
    Gère les backticks markdown et les caractères parasites.
    """
    text = text.strip()

    # Supprime les backticks markdown
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    # Extrait le JSON entre la première { et la dernière }
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return match.group(0).strip()

    return text.strip()
