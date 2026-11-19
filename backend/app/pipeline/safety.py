"""Rule-based safety / intent routing in English, Hindi and Hinglish, and reviewed response templates.

Runs BEFORE retrieval. Severity order wins when several patterns match. Rules are deliberately
recall-biased for emergencies and distress. (An LLM classifier could be layered on top; the rules alone
must always be sufficient for the emergency path.)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

EMERGENCY_NUMBERS = ["112", "102", "101", "108"]  # as listed in the CarePal iOS app listing
WHATSAPP_URL = "https://wa.me/917855816586"  # public link on thecarepal.com
WHATSAPP_DISPLAY = "+91 78558 16586"


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.I | re.U)


EMERGENCY = _rx(
    r"chest pain", r"can'?t breathe|cannot breathe|difficulty breathing|trouble breathing|shortness of breath",
    r"unconscious|unresponsive|not responding|passed out|fainted", r"seizure|convulsion", r"\bstroke\b",
    r"heart attack", r"bleeding (heavily|a lot|badly)|severe bleeding|won'?t stop bleeding",
    r"(has|have) fallen and|fell down and|fallen and (can'?t|cannot)", r"\bchoking\b", r"overdos|poison",
    r"ambulance (now|urgent|immediately|chahiye)", r"seene mein dard|saans nahi|saans lene mein|behosh",
    r"\bgir (gaye|gayi|gaya)\b|khoon (beh|nikal)|daura pad|dil ka daura|heart attack aaya",
    r"सीने में दर्द|साँस नहीं|सांस नहीं|बेहोश|दौरा|खून बह|गिर गए|गिर गई|दिल का दौरा",
)
DISTRESS = _rx(
    r"suicid|kill myself|end my life|want to die|self[- ]?harm|hurt myself|no reason to live",
    r"mar jana chahta|marna chahta|marna chahti|jaan de dun|khud ko khatam|aatmahatya|jeena nahi chahta|jeena nahi chahti",
    r"आत्महत्या|मरना चाहता|मरना चाहती|जान दे दूं|खुद को खत्म|जीना नहीं चाहता|जीना नहीं चाहती",
)
INJECTION = _rx(
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"(reveal|show|print|repeat|tell me) (me )?(your |the )?(system )?(prompt|instructions)",
    r"pretend (to be|you are)|jailbreak|developer mode|disregard (your|the) (rules|instructions)|you are now",
    r"pehle ke (instructions|nirdesh) (ignore|bhool)|पिछले निर्देश (अनदेखा|भूल)",
)
WANTS_HUMAN = _rx(
    r"(talk|speak|connect|chat) (to|with) (a |an |the )?(real )?(person|human|agent|someone|representative|executive|team)",
    r"\bcall me\b|call ?back|callback|real person|human agent",
    r"insaan se baat|kisi se baat|team se baat|mujhe call|call kar(o|na|ein)|baat karni hai",
    r"किसी इंसान से|टीम से बात|मुझे कॉल|कॉल कर",
)
COMPLAINT = _rx(
    r"complain|did ?n'?t (come|arrive|show up)|not arrived|no[- ]show|\brude\b|misbehav|\bstole\b|theft|abus(e|ed|ive)|"
    r"neglect|unsafe|harass|bad service|terrible service|worst service",
    r"shikayat|nahi aaya|nahin aaya|nahi aayi|nahin aayi|chori|badtameez|lapparwahi|galat vyavhar",
    r"शिकायत|नहीं आया|नहीं आई|चोरी|बदतमीज़|बदतमीज|लापरवाही",
)
MEDICAL = _rx(
    r"\b(dose|dosage|overdose)\b", r"how (much|many) (mg|tablets?|pills?|medicine)", r"what (medicine|medication|drug|tablet)s? (should|can|to)",
    r"is it (safe|ok|okay) to (take|give|combine|mix)", r"(can|should) (i|we) (take|give|stop|skip|double)\b",
    r"diagnos", r"is (it|this|that) (serious|dangerous)", r"side effects? of", r"prescri(be|ption) (me|for)",
    r"my (mother|father|mom|dad|wife|husband|grandmother|grandfather)\b.{0,40}\b(has|have|having)\b.{0,40}\b(fever|pain|cough|vomit|rash|swelling|infection)",
    r"kaunsi dawa|kaun si dawa|kaunsi dawai|kaun si dawai|dawai (kitni|de)|kitni (dawai|goli)|dawa dena|dawai lena|bukhar (hai|mein)|dard (hai|ho raha)",
    r"कौन सी दवा|कौनसी दवा|दवा (कितनी|दें|दे)|खुराक|बुखार (है|में)|दर्द (है|हो रहा)",
)
ACCOUNT = _rx(
    r"\bmy (nurse|caregiver|invoice|bill|booking|appointment|payment|account|attendance|schedule)\b",
    r"where is my nurse", r"\bmera (nurse|bill|invoice|booking|appointment|payment|account)\b", r"\bmeri (booking|appointment)\b",
    r"मेरा (नर्स|बिल|बुकिंग|इनवॉइस|अकाउंट|पेमेंट)|मेरी (बुकिंग|अपॉइंटमेंट)",
)
PRIVACY_REQUEST = _rx(
    r"delete my (data|account|information)|remove my (data|account)|access my data|correct my data|data deletion",
    r"mera data (delete|hata|mita)|data delete kar", r"मेरा डेटा (हटा|डिलीट|मिटा)",
)

CITIES = ("delhi|mumbai|pune|bangalore|bengaluru|chennai|kolkata|hyderabad|lucknow|jaipur|indore|ahmedabad|noida|"
          "gurgaon|gurugram|chandigarh|patna|bhopal|nagpur|kochi|surat|dehradun|ranchi|goa|kanpur|varanasi")
TOPICS: dict[str, re.Pattern[str]] = {
    "price": _rx(r"\b(price|prices|pricing|cost|costs|charges?|fees?|rates?|how much|discount|quote|cheap|expensive)\b",
                 r"per (hour|day|month|week)", r"kitna (paisa|kharcha|lagega|charge)|kitne (paise|rupay|rupaye)|kharcha|kimat|\bdaam\b|charges kitne|fees kitni",
                 r"कीमत|खर्च|शुल्क|कितना (पैसा|खर्च)|कितने (पैसे|रुपये)|दाम"),
    "city": _rx(r"(which|what) (cities|areas|locations)", r"do you (serve|operate|provide|cover)\b.{0,25}\b(in|at)\s+(?!home\b|the home\b|my home\b|their home\b)", r"service area",
                rf"\b(available|serve|service|services|office|operate)\b.{{0,15}}\b({CITIES})\b",
                r"(kis|kaun se) (shahar|city|jagah)", rf"\b({CITIES}) (mein|me) (available|milega|service)",
                r"किस शहर|कौन से शहर"),
    "availability": _rx(r"how (soon|quickly|fast)", r"start (date|tomorrow|today)", r"available (today|tomorrow|now|immediately)",
                        r"kab tak|kitni jaldi|aaj hi|kal se|कितनी जल्दी|कब तक|आज ही|कल से"),
    "insurance": _rx(r"insurance|mediclaim|cashless|reimburse|\btpa\b|ayushman|cghs", r"बीमा"),
    "credentials": _rx(r"\bqualification|\bqualified\b|\bcertified\b|\bdegree\b|licen[cs]e|background[- ]check|police verification|\bb\.?sc\b|\bgnm\b",
                       r"योग्यता|पुलिस वेरिफिकेशन"),
}
# A topic counts as covered only when a retrieved chunk states it explicitly (not merely mentions the word).
TOPIC_EVIDENCE: dict[str, re.Pattern[str]] = {
    "price": re.compile(r"(?:₹|rs\.?|inr)\s*\d|\d[\d,]*\s*(?:rupees|rs\b|inr\b)|\bper (?:hour|day|month|week)\b", re.I),
    "city": re.compile(r"cities (?:served|covered)|we (?:serve|operate in)|service area[s]? (?:include|are)|available in [A-Z]", re.I),
    "availability": re.compile(r"\b(?:within|in)\s+\d+\s*(?:minutes?|mins?|hours?|days?)\b|same[- ]day", re.I),
    "insurance": re.compile(r"\binsurance (?:is|are|accepted|covered|claims?)|cashless", re.I),
    "credentials": re.compile(r"\b(?:b\.?sc|gnm|anm|police verification|background[- ]check(?:ed)?)\b", re.I),
}

ROUTES_TEMPLATED = {"emergency", "distress", "injection", "wants_human", "complaint", "medical_advice", "account_request"}


@dataclass(frozen=True)
class SafetyResult:
    route: str  # emergency|distress|injection|wants_human|complaint|medical_advice|account_request|privacy_request|unpublished_info|in_scope
    topic: str | None = None
    priority: str = "normal"


def classify(text: str) -> SafetyResult:
    checks = [
        ("emergency", EMERGENCY, "urgent"), ("distress", DISTRESS, "urgent"), ("injection", INJECTION, "normal"),
        ("wants_human", WANTS_HUMAN, "normal"), ("complaint", COMPLAINT, "high"), ("medical_advice", MEDICAL, "normal"),
        ("account_request", ACCOUNT, "normal"), ("privacy_request", PRIVACY_REQUEST, "normal"),
    ]
    for route, rx, prio in checks:
        if rx.search(text):
            return SafetyResult(route, None, prio)
    for topic, rx in TOPICS.items():
        if rx.search(text):
            return SafetyResult("unpublished_info", topic)
    return SafetyResult("in_scope")


def topic_is_covered(topic: str, texts: list[str]) -> bool:
    rx = TOPIC_EVIDENCE.get(topic)
    return bool(rx and any(rx.search(t) for t in texts))


NUMS = ", ".join(EMERGENCY_NUMBERS)
TEMPLATES: dict[str, dict[str, str]] = {
    "emergency": {
        "en": f"This may be an emergency. Please call an emergency number right now: {NUMS} (the emergency numbers listed in the CarePal app). Do not wait for a chat reply. If you can, stay with the person and follow the emergency operator's instructions.",
        "hi": f"यह आपात स्थिति हो सकती है। कृपया अभी आपातकालीन नंबर पर कॉल करें: {NUMS} (CarePal ऐप में दिए गए आपातकालीन नंबर)। चैट के जवाब का इंतज़ार न करें। हो सके तो मरीज़ के साथ रहें और आपातकालीन ऑपरेटर की बात मानें।",
        "hinglish": f"Yeh emergency ho sakti hai. Please abhi emergency number par call karein: {NUMS} (CarePal app mein diye gaye emergency numbers). Chat ke jawab ka wait na karein. Ho sake to mareez ke saath rahein aur emergency operator ki baat maniye.",
    },
    "distress": {
        "en": "I'm really sorry you're going through this, and I'm glad you said it. You don't have to face it alone. If you might act on thoughts of harming yourself, please call 112 now or ask someone you trust to be with you. If you'd like, you can also leave your name and number and ask the CarePal team to follow up.",
        "hi": "आप जिस दौर से गुज़र रहे हैं, उसके लिए मुझे सचमुच दुख है, और आपने बताया यह अच्छा किया। आपको इसे अकेले नहीं झेलना है। अगर आपको खुद को नुकसान पहुँचाने के विचार आ रहे हैं, तो कृपया अभी 112 पर कॉल करें या किसी भरोसेमंद व्यक्ति को अपने पास बुलाएँ। चाहें तो अपना नाम और नंबर छोड़ सकते हैं ताकि CarePal टीम से संपर्क का अनुरोध दर्ज हो।",
        "hinglish": "Aap jis daur se guzar rahe hain uske liye mujhe sach mein dukh hai, aur aapne bataya yeh achha kiya. Aapko yeh akele nahi jhelna hai. Agar aapko khud ko nuksaan pahunchane ke vichaar aa rahe hain, to please abhi 112 par call karein ya kisi bharosemand vyakti ko apne paas bulayein. Chahein to apna naam aur number chhod sakte hain taaki CarePal team se sampark ka request darj ho.",
    },
    "medical_advice": {
        "en": "I can't give medical advice, diagnose, or suggest medicines or doses. Please speak to a doctor or nurse. In an emergency call 112, 102, 101 or 108. TheCarePal's published pages describe doctor consultations by video, phone or in-home visit.",
        "hi": "मैं चिकित्सीय सलाह, निदान, दवाइयाँ या खुराक नहीं बता सकता/सकती। कृपया किसी डॉक्टर या नर्स से बात करें। आपात स्थिति में 112, 102, 101 या 108 पर कॉल करें। TheCarePal के प्रकाशित पृष्ठों के अनुसार डॉक्टर परामर्श वीडियो, फोन या घर पर उपलब्ध है।",
        "hinglish": "Main medical advice, diagnosis, dawaiyan ya dose nahi bata sakta/sakti. Please kisi doctor ya nurse se baat karein. Emergency mein 112, 102, 101 ya 108 par call karein. TheCarePal ke published pages ke hisaab se doctor consultation video, phone ya ghar par available hai.",
    },
    "account_request": {
        "en": "I can't see anyone's account, nurse schedule, bookings or invoices in this chat. TheCarePal's website says its in-app assistant 'Lisa' can help with your own nurse, appointments and support tickets, and you can also use the CarePal app. You can leave a request here too.",
        "hi": "मैं इस चैट में किसी का खाता, नर्स का शेड्यूल, बुकिंग या इनवॉइस नहीं देख सकता/सकती। TheCarePal की वेबसाइट के अनुसार ऐप में 'Lisa' असिस्टेंट आपकी नर्स, अपॉइंटमेंट और सपोर्ट टिकट में मदद कर सकता है; आप CarePal ऐप भी इस्तेमाल कर सकते हैं। आप यहाँ अनुरोध भी छोड़ सकते हैं।",
        "hinglish": "Main is chat mein kisi ka account, nurse ka schedule, booking ya invoice nahi dekh sakta/sakti. TheCarePal ki website ke hisaab se app mein 'Lisa' assistant aapki nurse, appointment aur support ticket mein madad kar sakta hai; aap CarePal app bhi use kar sakte hain. Aap yahan request bhi chhod sakte hain.",
    },
    "injection": {
        "en": "I can only help with questions about TheCarePal's published services and policies, so I can't follow that instruction. What would you like to know about CarePal's services?",
        "hi": "मैं केवल TheCarePal की प्रकाशित सेवाओं और नीतियों के बारे में प्रश्नों में मदद कर सकता/सकती हूँ, इसलिए यह निर्देश नहीं मान सकता/सकती। आप CarePal की सेवाओं के बारे में क्या जानना चाहते हैं?",
        "hinglish": "Main sirf TheCarePal ki published services aur policies ke baare mein madad kar sakta/sakti hoon, isliye yeh instruction nahi maan sakta/sakti. Aap CarePal ki services ke baare mein kya jaanna chahte hain?",
    },
    "wants_human": {
        "en": "Of course. Please share your name and phone number and agree to be contacted, and I'll record a request for the CarePal team. (This prototype only saves the request; it does not contact anyone automatically.) You can also message TheCarePal on WhatsApp at " + WHATSAPP_DISPLAY + ".",
        "hi": "ज़रूर। कृपया अपना नाम और फ़ोन नंबर बताएँ और संपर्क के लिए सहमति दें, मैं CarePal टीम के लिए अनुरोध दर्ज कर दूँगा/दूँगी। (यह प्रोटोटाइप केवल अनुरोध सहेजता है; किसी को अपने-आप सूचित नहीं करता।) आप WhatsApp पर " + WHATSAPP_DISPLAY + " पर भी संदेश भेज सकते हैं।",
        "hinglish": "Zaroor. Please apna naam aur phone number batayein aur contact ke liye consent dein, main CarePal team ke liye request record kar dunga/dungi. (Yeh prototype sirf request save karta hai; kisi ko apne-aap inform nahi karta.) Aap WhatsApp par " + WHATSAPP_DISPLAY + " par bhi message kar sakte hain.",
    },
    "complaint": {
        "en": "I'm sorry this happened. I can't investigate or resolve complaints here, but I can record a request for the CarePal team: please share your name and phone number and agree to be contacted. (This prototype only saves the request; it does not contact anyone automatically.) For anything unsafe or urgent, call 112.",
        "hi": "इसके लिए मुझे खेद है। मैं यहाँ शिकायत की जाँच या समाधान नहीं कर सकता/सकती, लेकिन CarePal टीम के लिए अनुरोध दर्ज कर सकता/सकती हूँ: कृपया अपना नाम और फ़ोन नंबर बताएँ और संपर्क के लिए सहमति दें। (यह प्रोटोटाइप केवल अनुरोध सहेजता है; किसी को अपने-आप सूचित नहीं करता।) किसी असुरक्षित या आपातकालीन स्थिति में 112 पर कॉल करें।",
        "hinglish": "Iske liye mujhe khed hai. Main yahan complaint ki jaanch ya samaadhaan nahi kar sakta/sakti, lekin CarePal team ke liye request record kar sakta/sakti hoon: please apna naam aur phone number batayein aur contact ke liye consent dein. (Yeh prototype sirf request save karta hai; kisi ko apne-aap inform nahi karta.) Kisi unsafe ya urgent situation mein 112 par call karein.",
    },
    "abstain": {
        "en": f"I couldn't find this in TheCarePal's published information, and I don't want to guess. You can leave your name and phone number to ask the team to follow up (this prototype only saves the request), or message TheCarePal on WhatsApp at {WHATSAPP_DISPLAY}.",
        "hi": f"मुझे यह जानकारी TheCarePal की प्रकाशित सामग्री में नहीं मिली, और मैं अंदाज़ा नहीं लगाना चाहता/चाहती। आप अपना नाम और फ़ोन नंबर छोड़कर टीम से संपर्क का अनुरोध कर सकते हैं (यह प्रोटोटाइप केवल अनुरोध सहेजता है), या WhatsApp पर {WHATSAPP_DISPLAY} पर संदेश भेज सकते हैं।",
        "hinglish": f"Mujhe yeh jaankari TheCarePal ki published information mein nahi mili, aur main andaza nahi lagana chahta/chahti. Aap apna naam aur phone number chhod kar team se sampark ka request kar sakte hain (yeh prototype sirf request save karta hai), ya WhatsApp par {WHATSAPP_DISPLAY} par message kar sakte hain.",
    },
    "no_index": {
        "en": "The assistant's knowledge base is not available right now. Please try again later or message TheCarePal on WhatsApp at " + WHATSAPP_DISPLAY + ".",
        "hi": "सहायक का ज्ञान-आधार अभी उपलब्ध नहीं है। कृपया बाद में कोशिश करें या WhatsApp पर " + WHATSAPP_DISPLAY + " पर संदेश भेजें।",
        "hinglish": "Assistant ka knowledge base abhi available nahi hai. Please baad mein try karein ya WhatsApp par " + WHATSAPP_DISPLAY + " par message karein.",
    },
}
TOPIC_NOTES: dict[str, dict[str, str]] = {
    "price": {"en": "The pages I have don't list prices.", "hi": "मेरे पास मौजूद पृष्ठों में कीमतें नहीं दी गई हैं।",
              "hinglish": "Mere paas maujood pages mein prices nahi diye gaye hain."},
    "city": {"en": "The pages I have don't list the cities or areas served.", "hi": "मेरे पास मौजूद पृष्ठों में सेवा वाले शहरों या क्षेत्रों की सूची नहीं है।",
             "hinglish": "Mere paas maujood pages mein service wale cities ya areas ki list nahi hai."},
    "availability": {"en": "The pages I have don't state start dates, availability or response times.", "hi": "मेरे पास मौजूद पृष्ठों में शुरू होने की तारीख़, उपलब्धता या प्रतिक्रिया समय नहीं बताया गया है।",
                     "hinglish": "Mere paas maujood pages mein start date, availability ya response time nahi bataya gaya hai."},
    "insurance": {"en": "The pages I have don't mention insurance coverage.", "hi": "मेरे पास मौजूद पृष्ठों में बीमा कवरेज का उल्लेख नहीं है।",
                  "hinglish": "Mere paas maujood pages mein insurance coverage ka zikr nahi hai."},
    "credentials": {"en": "The pages I have don't give caregiver qualification or background-check details.", "hi": "मेरे पास मौजूद पृष्ठों में देखभालकर्ताओं की योग्यता या बैकग्राउंड जाँच का विवरण नहीं है।",
                    "hinglish": "Mere paas maujood pages mein caregivers ki qualification ya background-check ka vivaran nahi hai."},
}
LEAD_INS = {
    "en": "Here is what TheCarePal's published pages say:",
    "hi": "TheCarePal के प्रकाशित पृष्ठों के अनुसार (स्रोत अंग्रेज़ी में हैं):",
    "hinglish": "TheCarePal ke published pages ke hisaab se (sources English mein hain):",
}


def template(key: str, lang: str) -> str:
    return TEMPLATES[key].get(lang) or TEMPLATES[key]["en"]
