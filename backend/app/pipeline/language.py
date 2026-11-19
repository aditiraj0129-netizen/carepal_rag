"""Detect English / Hindi (Devanagari) / Hinglish (Roman-script Hindi) without any external service."""
from __future__ import annotations

import re

# Frequent Hindi words that are not English words (ambiguous ones such as 'to', 'me', 'hi' are excluded).
HINGLISH_WORDS = frozenset(
    """hai hain hoga hogi kya ke ka ki ko mein se par aur ya bhi toh nahi nahin kaise kaun kab kyun kyu
    kitna kitne kitni chahiye milega milta milti mil sakta sakti sakte karna karne kare karo karein kijiye
    aap aapka aapke aapki hum humare mujhe mere meri mera mummy papa dada dadi nani nana bujurg buzurg
    dekhbhal paisa paise wapas kaam rakhna lagta hota hoti abhi raat ghar dawai dawa bimar bimari bukhar
    dard saans behosh madad batao bataiye bataye lekin isliye kyunki agar wala wali wale ek liye tha thi
    raha rahi rahe hote shahar jagah kharcha kimat shikayat baat karni dena dete lena kal aaj yahan wahan""".split()
)
_WORD = re.compile(r"[A-Za-z']+")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    deva = len(_DEVANAGARI.findall(text))
    if deva / len(letters) >= 0.3:
        return "hi"
    words = [w.lower() for w in _WORD.findall(text)]
    hits = sum(1 for w in words if w in HINGLISH_WORDS)
    if hits >= 2 or (hits >= 1 and hits / max(len(words), 1) >= 0.25):
        return "hinglish"
    return "en"
