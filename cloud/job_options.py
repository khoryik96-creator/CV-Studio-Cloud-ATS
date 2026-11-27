"""Persist the user's formatting choices; OCR remains server policy."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Options:
    alignment: str = "left"
    correct_language: bool = False
    neutral_gender: bool = False

    def validate(self, module):
        if self.alignment not in ("left","justify") or type(self.correct_language) is not bool or type(self.neutral_gender) is not bool:
            raise ValueError("Invalid job options")
        if self.neutral_gender and module!="cv_blinding":
            raise ValueError("Gender neutralization requires blinding")
        return self
