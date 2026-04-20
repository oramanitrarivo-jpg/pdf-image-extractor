PROMPT_ASSOCIATE = """
Tu analyses des pages d'un catalogue produits PDF.
Ta mission : extraire les informations structurées du produit indiqué
et identifier quelles images de la liste correspondent à ce produit.

Produit à extraire : {nom_produit}

Règles :
- Le descriptif doit être une phrase claire et commerciale (2-4 phrases max)
- Les caractéristiques sont des données techniques factuelles
  (température, pression, matière, dimensions, etc.)
- Les indices d'images correspondent aux positions dans la liste
  des images acceptées fournie (commence à 0)
- N'associe que les images qui représentent visuellement CE produit spécifique
- Si aucune image ne correspond à ce produit, retourne une liste vide

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "nom": "nom exact du produit",
  "descriptif": "description commerciale du produit",
  "caracteristiques": "caracteristique1, caracteristique2, ...",
  "images_indices": [liste des indices des images associées à ce produit]
}
""".strip()
