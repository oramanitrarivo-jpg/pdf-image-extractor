import json
import re


def clean_json_response(text: str) -> str:
    """
    Extrait le premier JSON valide depuis une réponse Claude.
    Gère les backticks, le texte parasite avant/après, et les JSON malformés.
    """
    text = text.strip()

    # Supprime les backticks markdown
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                text = part
                break

    # Tente d'extraire le premier JSON valide avec JSONDecoder
    decoder = json.JSONDecoder()
    for i, char in enumerate(text):
        if char == "{":
            try:
                obj, _ = decoder.raw_decode(text, i)
                return json.dumps(obj)
            except json.JSONDecodeError:
                continue

    # Fallback — regex basique
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return match.group(0).strip()

    return text.strip()
