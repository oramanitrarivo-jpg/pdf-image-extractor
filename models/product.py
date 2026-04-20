from dataclasses import dataclass, field
from models.image import Image


@dataclass
class Product:
    nom:              str
    descriptif:       str
    caracteristiques: str
    images:           list[Image] = field(default_factory=list)
    source_pdf:       str = ""
    date_ajout:       str = ""

    def to_dict(self) -> dict:
        return {
            "nom":              self.nom,
            "descriptif":       self.descriptif,
            "caracteristiques": self.caracteristiques,
            "images":           [img.to_dict() for img in self.images],
            "source_pdf":       self.source_pdf,
            "date_ajout":       self.date_ajout,
        }
