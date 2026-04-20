def clean_json_response(text: str) -> str:
    """
    Nettoie les backticks markdown éventuels autour du JSON
    retourné par Claude.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()
