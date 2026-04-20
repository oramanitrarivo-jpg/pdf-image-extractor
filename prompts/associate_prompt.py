PROMPT_ASSOCIATE = """
Tu analyses des pages d'un catalogue produits PDF.
Ta mission : extraire les informations structurées du produit indiqué
et identifier quelles images de la liste correspondent UNIQUEMENT à ce produit.

Produit à extraire : {nom_produit}

Règles strictes :
- Le descriptif doit être une phrase claire et commerciale (2-4 phrases max)
- Les caractéristiques sont des données techniques factuelles
  (température, pression, matière, dimensions, etc.)
- Les indices d'images correspondent aux positions dans la liste
  des images acceptées fournie (commence à 0)

Règles strictes pour l'association des images :
- N'associe QUE les images qui représentent visuellement CE produit spécifique
- Si plusieurs produits sont visibles sur la même page, chaque image
  appartient à UN SEUL produit — ne partage jamais une image entre deux produits
- Si une image est positionnée à côté d'un autre produit sur la page,
  ne l'inclus PAS dans les indices de CE produit
- Si tu n'es pas sûr à quelle produit appartient une image, ne l'inclus pas
- Si aucune image ne correspond à ce produit, retourne une liste vide

Réponds UNIQUEMENT avec ce JSON, sans texte autour :
{
  "nom": "nom exact du produit",
  "descriptif": "description commerciale du produit",
  "caracteristiques": "caracteristique1, caracteristique2, ...",
  "images_indices": [liste des indices des images associées UNIQUEMENT à ce produit]
}
""".strip()
