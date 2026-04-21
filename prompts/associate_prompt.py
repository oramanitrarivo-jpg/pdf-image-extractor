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
- Si tu n'es pas sûr à quel produit appartient une image, ne l'inclus pas
- Si aucune image ne correspond à ce produit, retourne une liste vide

IMPORTANT : Ta réponse doit être UNIQUEMENT ce bloc JSON, rien d'autre.
Pas de texte avant, pas de texte après, pas d'explication.
Commence directement par {{ et termine par }}.

Exemple de réponse attendue :
{{
  "nom": "Nom du produit",
  "descriptif": "Description commerciale du produit.",
  "caracteristiques": "Caracteristique1, caracteristique2",
  "images_indices": [0, 2]
}}

Ta réponse pour le produit '{nom_produit}' :
""".strip()
