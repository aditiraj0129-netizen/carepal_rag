"""Query understanding: build an English search query from English / Hindi / Hinglish input.

The corpus is English-only, so Hindi and Hinglish questions are mapped to English search terms with a
small hand-written care glossary (auditable, no model needed). When an LLM provider is configured it can
refine the rewrite; if it fails we silently keep the rule-based plan.
"""
from __future__ import annotations

import logging
import re

from app.llm.base import LLMClient, LLMError
from app.retrieval.hybrid import QueryPlan
from app.retrieval.tokenization import HINGLISH_STOP, normalize

log = logging.getLogger(__name__)

# Roman-script phrases first (longest match), then single words.
PHRASES = {
    "paisa wapas": "refund", "paise wapas": "refund", "money back": "refund", "dekh bhal": "care",
    "kitna kharcha": "cost price", "kitne paise": "price cost", "kitna paisa": "price cost",
    "kitne rupay": "price cost", "kitne rupaye": "price cost", "part time": "part-time",
    "full time": "full-time", "24 ghante": "24/7 live-in", "chaubis ghante": "24/7 live-in",
    "ghar par": "home", "ghar pe": "home", "ghar mein": "home", "seene mein dard": "chest pain",
    "saans nahi": "breathing difficulty",
}
WORDS = {
    "dekhbhal": "care", "bujurg": "elderly", "buzurg": "elderly", "budhape": "elderly", "buddhe": "elderly",
    "dawai": "medicine", "dawa": "medicine", "dawaiyan": "medicine", "bimar": "sick", "bimari": "illness",
    "yaaddaasht": "memory", "yaadasht": "memory", "yaddasht": "memory", "bhulakkad": "dementia memory",
    "bachcha": "baby", "bachche": "baby", "bachchon": "baby", "shishu": "baby", "navjaat": "newborn baby",
    "kharcha": "cost price", "kimat": "price", "daam": "price", "shulk": "fee charges", "paisa": "payment",
    "gopaniyata": "privacy", "shartein": "terms", "niyam": "terms", "ghar": "home", "raat": "night",
    "seva": "service", "sewa": "service", "suvidha": "service", "mareez": "patient", "marij": "patient",
    "dada": "elderly grandfather", "dadi": "elderly grandmother", "nani": "elderly grandmother",
    "nana": "elderly grandfather", "mummy": "mother", "papa": "father", "maa": "mother", "pitaji": "father",
    "ayah": "caregiver", "nursing": "nurse", "aapatkaal": "emergency", "sampark": "contact",
    "shikayat": "complaint", "wapas": "refund", "hatana": "delete", "mitana": "delete", "baat": "contact",
    "jankari": "information", "madad": "help", "shahar": "city", "ilaaj": "treatment",
}
DEVANAGARI = {
    "बुजुर्ग": "elderly", "बुज़ुर्ग": "elderly", "वृद्ध": "elderly", "देखभाल": "care", "देखरेख": "care",
    "रिफंड": "refund", "पैसे वापस": "refund", "पैसा वापस": "refund", "डिमेंशिया": "dementia",
    "भूलने की बीमारी": "dementia memory", "अल्जाइमर": "alzheimer", "अल्ज़ाइमर": "alzheimer", "नर्स": "nurse",
    "डॉक्टर": "doctor", "बच्चे": "baby", "बच्चा": "baby", "शिशु": "baby", "नवजात": "newborn baby",
    "कीमत": "price cost", "खर्च": "cost price", "शुल्क": "fee charges", "गोपनीयता": "privacy",
    "प्राइवेसी": "privacy", "नियम": "terms", "शर्तें": "terms", "आपातकालीन": "emergency",
    "आपातकाल": "emergency", "इमरजेंसी": "emergency", "एम्बुलेंस": "ambulance", "दवा": "medicine",
    "दवाई": "medicine", "याददाश्त": "memory", "घर": "home", "संपर्क": "contact", "फोन": "phone",
    "व्हाट्सएप": "whatsapp", "ऑटिज्म": "autism", "थेरेपी": "therapy", "परामर्श": "consultation",
    "अस्पताल": "hospital", "सर्जरी": "surgery", "लाइव-इन": "live-in", "पार्ट-टाइम": "part-time",
    "पार्ट टाइम": "part-time", "केयरगिवर": "caregiver", "देखभालकर्ता": "caregiver", "आया": "caregiver",
    "डेटा": "data", "हटाना": "delete", "मिटाना": "delete", "शिकायत": "complaint", "सेवा": "service",
    "सेवाएं": "services", "सेवाएँ": "services", "मानसिक": "mental", "तनाव": "stress", "अकेलापन": "loneliness",
    "माँ": "mother", "मां": "mother", "पिता": "father", "पापा": "father", "दादी": "elderly grandmother",
    "दादा": "elderly grandfather", "कौन": "", "क्या": "", "कैसे": "", "है": "", "हैं": "", "में": "",
    "के": "", "की": "", "का": "", "को": "", "मुझे": "", "मेरी": "", "मेरा": "", "मेरे": "", "और": "",
}


FOLLOW_UP = re.compile(
    r"^(and|also|what about|how about|why|how so|really|ok(ay)?|then|so|it|its|that|this|those|they|them|"
    r"aur|isse?|us(ke|ka|ki|se)|iska|iski|woh|wo|ye|yeh|phir|और|इसका|इसकी|उसका|उसकी|वो|ये|फिर)\b",
    re.IGNORECASE)


def glossary_rewrite(text: str, language: str) -> tuple[str, list[str]]:
    if language == "en":
        return text, []
    hits: list[str] = []
    low = normalize(text)
    for phrase, eng in PHRASES.items():
        if phrase in low:
            low = low.replace(phrase, f" {eng} ")
            hits.append(phrase)
    for deva, eng in sorted(DEVANAGARI.items(), key=lambda kv: -len(kv[0])):
        if deva in low:
            low = low.replace(deva, f" {eng} ")
            if eng:
                hits.append(deva)
    out: list[str] = []
    for tok in re.findall(r"[a-z0-9'/\-]+", low):
        if tok in WORDS:
            out.append(WORDS[tok])
            hits.append(tok)
        elif tok not in HINGLISH_STOP:
            out.append(tok)
    english = " ".join(out).strip()
    return english or text, hits


def build_plan(message: str, language: str, previous_question: str | None = None,
               llm: LLMClient | None = None) -> QueryPlan:
    english, hits = glossary_rewrite(message, language)
    source = "rules"
    if llm is not None:
        try:
            data = llm.complete_json([
                {"role": "system", "content": (
                    "Rewrite the user's question as a short English search query for a home-care company's "
                    "website. Keep every concrete term (service names, 'refund', 'price'). Respond with JSON: "
                    '{"english_query": "..."} and nothing else.')},
                {"role": "user", "content": message}])
            candidate = str(data.get("english_query", "")).strip()
            if candidate:
                english, source = candidate, "llm"
        except LLMError:
            log.warning("LLM rewrite failed; using rule-based rewrite")
    # Carry context forward ONLY for genuine follow-ups ("and for babies?", "what about it?").
    # A short but self-contained question ("refund policy") must not inherit the previous topic.
    if previous_question and len(english.split()) < 4 and FOLLOW_UP.search(message.strip()):
        english = f"{previous_question} {english}".strip()
    return QueryPlan(original=message, english_query=english, language=language, source=source,
                     glossary_hits=hits)
