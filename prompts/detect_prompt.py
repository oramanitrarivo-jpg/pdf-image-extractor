PROMPT_DETECT = """
Tu analyses des pages d'un catalogue produits PDF.
Ta mission : identifier tous les produits présents dans ces pages.

Un produit est une entité commerciale distincte avec un nom et une description.
Ne confonds pas un produit avec une variante (ex: différentes tailles du même produit).

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "produits": [
    {
      "nom": "nom exact du produit tel qu'il apparaît",
      "pages": [liste des numéros de pages où ce produit apparaît, commence à 1]
    }
  ]
}

Si aucun produit n'est détectable, retourne : { "produits": [] }
""".strip()
