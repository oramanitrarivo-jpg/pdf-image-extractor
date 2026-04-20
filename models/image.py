from dataclasses import dataclass, field


@dataclass
class Image:
    data_b64:   str
    media_type: str
    width:      int
    height:     int
    # Enrichi après classification
    confidence: float = 0.0
    category:   str   = "other"
    reason:     str   = ""
    accepted:   bool  = False

    def to_dict(self) -> dict:
        return {
            "data_b64":   self.data_b64,
            "media_type": self.media_type,
            "width":      self.width,
            "height":     self.height,
            "confidence": self.confidence,
            "category":   self.category,
            "reason":     self.reason,
        }
