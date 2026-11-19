"""Text normalisation and tokenisation for BM25 and query-term analysis (no external data files)."""
from __future__ import annotations

import re
import unicodedata

import snowballstemmer

_STEMMER = snowballstemmer.stemmer("english")

EN_STOP = frozenset(
    "a an the and or of to in on for with at by from is are was were be been being it its this that these "
    "those as if then than so do does did can could should would will may might i you he she we they me my "
    "your our their us them what which who whom how when where why not no yes also any all each more most "
    "such there here about into over under again very just please tell".split()
)
HINGLISH_STOP = frozenset(
    "hai hain hoga hogi ho hota hoti kya ke ka ki ko mein se par aur ya bhi toh kar karna karne kare "
    "kuch koi mujhe mere meri mera hum humare aap aapka aapke aapki ek hi nahi nahin kaise kaun kab "
    "kyun kyu liye lie wala wali wale tha thi the raha rahi rahe sakta sakti sakte chahiye milega milta milti "
    "mil dete dena deta dete lete lena batao bataiye bataye btao chahta chahti hote kitna kitne kitni kaisa "
    "kaisi konsa kaunsa kahan kahaan kyunki agar magar yahan wahan".split()
)
STOP = EN_STOP | HINGLISH_STOP

SYNONYMS = {
    "alzeihmer": "alzheimer", "alzheimers": "alzheimer", "alzhaimer": "alzheimer",
    "caretaker": "caregiver", "caretakers": "caregiver", "carer": "caregiver", "carers": "caregiver",
    "livein": "live", "refunds": "refund", "refunded": "refund", "nonrefundable": "refund",
    "dementias": "dementia", "nurses": "nurse", "doctors": "doctor",
}

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?|[ऀ-ॿ]+")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower().replace("’", "'")


def tokenize(text: str, *, stem: bool = True, drop_stop: bool = True) -> list[str]:
    out: list[str] = []
    for tok in _TOKEN.findall(normalize(text)):
        if tok.endswith("'s"):
            tok = tok[:-2]
        tok = SYNONYMS.get(tok, tok)
        if drop_stop and tok in STOP:
            continue
        if stem and tok.isascii() and tok.isalpha():
            tok = _STEMMER.stemWord(tok)
        out.append(tok)
    return out
