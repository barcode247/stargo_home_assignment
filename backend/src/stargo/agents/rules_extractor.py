"""Agent A, rules-only fallback: keyword extraction used when no LLM key is set.

It reads English, Dutch, German and Hebrew keywords. Anything else is reported
as unsupported so the lead lands in `needs review` instead of being judged on
words it cannot read.
"""

import re

from stargo.agents.schemas import DataProblem, Extraction, Intent, StatedCompanyFacts
from stargo.domain.models import CrmRecord, InboundMessage
from stargo.domain.normalize import normalize_country

SUPPORTED_LANGUAGES = frozenset({"en", "nl", "de", "he"})


class UnsupportedLanguage(Exception):
    pass


_STOPWORDS = {
    "en": {"the", "and", "to", "we", "our", "is", "a", "of", "for", "you", "i", "in", "with",
           "can", "this", "please", "would", "us", "my", "your", "are"},
    "nl": {"de", "het", "een", "en", "we", "niet", "voor", "op", "hebben", "geen", "dit",
           "bedankt", "van", "met", "ons", "onze", "wij", "graag", "uitnodiging", "moment"},
    "de": {"der", "die", "das", "und", "wir", "nicht", "für", "ist", "mit", "ein", "eine",
           "unser", "unsere", "kein", "sie", "bitte", "danke", "ich", "haben"},
    "fr": {"le", "la", "les", "et", "nous", "pour", "est", "une", "des", "pas", "avec",
           "vous", "je", "merci", "notre"},
    "es": {"el", "los", "las", "y", "nosotros", "para", "es", "una", "con", "por", "que",
           "gracias", "nuestro", "usted"},
}


def detect_language(text: str) -> str:
    if not text.strip():
        return "unknown"
    scripts = [("he", r"[֐-׿]"), ("ar", r"[؀-ۿ]"),
               ("ru", r"[Ѐ-ӿ]"), ("zh", r"[一-鿿]"),
               ("ja", r"[぀-ヿ]"), ("ko", r"[가-힯]")]
    for code, pattern in scripts:
        if re.search(pattern, text):
            return code
    words = re.findall(r"[a-zà-ÿ']+", text.lower())
    scores = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    best = max(scores.values())
    if best == 0:
        return "unknown"
    return "en" if scores["en"] == best else max(scores, key=lambda k: scores[k])


INTENT_RULES: list[tuple[Intent, list[str]]] = [
    ("unsubscribe", [r"\bunsubscribe\b", r"remove me from", r"\bopt[- ]?out\b",
                     r"stop (emailing|contacting|sending)", r"take me off", r"uitschrijven",
                     r"\bafmelden\b", r"\babmelden\b", r"austragen", r"להסיר אותי", r"הסירו"]),
    ("auto_reply", [r"out of (the )?office", r"automatic reply", r"auto[- ]?reply",
                    r"limited access to (my )?e-?mail", r"\bafwezig\b", r"abwesenheit",
                    r"nicht im büro", r"מחוץ למשרד"]),
    ("not_interested", [r"not interested", r"no interest", r"geen interesse",
                        r"kein interesse", r"לא מעוניינ"]),
    ("job_seeker", [r"\binternship\b", r"\bintern\b", r"\bjob\b", r"open (position|role)s?",
                    r"\bmy (cv|resume)\b", r"\bstudent\b", r"\bvacanc"]),
    ("investor", [r"funding round", r"next round", r"\binvest(or|ors|ment|ing)\b",
                  r"\bvaluation\b", r"\bportfolio compan"]),
    ("partnership", [r"\bpartnership\b", r"white[- ]label", r"\breseller\b",
                     r"\bpartner with\b"]),
    ("pilot", [r"\bpilot\b", r"proof of concept", r"\bpoc\b", r"פיילוט"]),
    ("demo", [r"\bdemo\b", r"show (us|me)", r"see (it|this|how)", r"\bcall\b", r"\bmeeting\b",
              r"\btalk\b", r"\bchat\b", r"send (me )?times", r"how (this|it) works",
              r"\bgesprek\b", r"\bafspraak\b", r"\btermin\b", r"gespräch", r"שיחה", r"דמו",
              r"פגישה"]),
    ("pricing", [r"\bpricing\b", r"\bprices?\b", r"\bcost\b", r"how much", r"\bkosten\b",
                 r"\bprijs\b", r"\bpreis\b", r"כמה עולה"]),
]

PROBLEM_RULES: list[tuple[str, list[str]]] = [
    ("invoice_reconciliation", [r"reconcil", r"invoice audit", r"invoices? against",
                                r"contracted rates", r"overcharg", r"freight audit"]),
    ("trade_document_checking", [r"letters? of credit", r"trade documents?",
                                 r"documentary (credit|collection)", r"before funds"]),
    ("document_extraction", [r"bills? of lading", r"air ?waybills?", r"\bawbs?\b", r"re-?key",
                             r"manual(ly)? (data |booking )?entry",
                             r"booking confirmations", r"from pdfs?", r"import declarations?",
                             r"customs (paperwork|declarations?|documents?)", r"packing lists?",
                             r"document (automation|extraction)", r"data entry",
                             r"handmatig", r"manuell", r"הקלדה ידנית"]),
    ("rate_quoting", [r"rate requests?", r"spot (rate|quote)s?", r"\bquot(e|es|ing|ation)\b",
                      r"\brfqs?\b", r"rate cards?", r"\btariffs?\b", r"\btender",
                      r"הצעות מחיר", r"מתמחר", r"\bofferte", r"\bangebot", r"\btarie"]),
]

_SELF_DESCRIPTION = re.compile(
    r"\b(we are|we're|i own|i run|i head|our company|i work (at|for)|i am)\b", re.IGNORECASE)

VERTICAL_RULES = [
    ("customs-broker", r"customs broker(age)?"),
    ("freight-forwarder", r"freight forward(er|ing)|\bforwarder\b"),
    ("3pl", r"\b3pl\b|third[- ]party logistics"),
    ("air-cargo", r"air cargo"),
    ("ground-handling", r"ground handl"),
    ("trucking", r"\btrucking\b|\bhaulage\b|\bhaulier\b"),
    ("trade-finance", r"trade financ"),
    ("carrier", r"\bshipping line\b|\bwe are a carrier\b"),
    ("software-vendor", r"\bsoftware\b"),
]

CITY_COUNTRY = {
    "haifa": "IL", "tel aviv": "IL", "ashdod": "IL", "jerusalem": "IL", "eilat": "IL",
    "rotterdam": "NL", "amsterdam": "NL", "antwerp": "BE", "brussels": "BE",
    "hamburg": "DE", "bremen": "DE", "berlin": "DE", "munich": "DE", "frankfurt": "DE",
    "vienna": "AT", "zurich": "CH", "basel": "CH",
    "london": "GB", "manchester": "GB", "felixstowe": "GB", "southampton": "GB",
    "copenhagen": "DK", "aarhus": "DK", "gothenburg": "SE", "stockholm": "SE", "oslo": "NO",
    "helsinki": "FI", "singapore": "SG",
    "new york": "US", "chicago": "US", "dallas": "US", "los angeles": "US", "miami": "US",
    "houston": "US", "atlanta": "US",
}

EMPLOYEES_RE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+)(?:[- ](?:person|people|employee|staff|strong)\b"
    r"| (?:employees|people|staff)\b)", re.IGNORECASE)
LOCATION_RE = re.compile(r"\b(?:in|based in|from|out of) ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)")
COMPANY_RE = re.compile(r"\b(?:at|for) ([A-Z][\w&-]+(?: [A-Z][\w&-]+){0,2})")
ROLE_PATTERNS = [
    (re.compile(r"\bI own\b", re.IGNORECASE), lambda m: "owner"),
    (re.compile(r"\bI(?: am|'m)? (?:the )?(?:co-)?founder\b", re.IGNORECASE),
     lambda m: "founder"),
    (re.compile(r"\bI (run|head|lead|manage) ([a-z][a-z &/-]{2,50}?)(?: at\b| for\b|[.,;!?]|$)",
                re.IGNORECASE),
     lambda m: ("manager of " if m.group(1).lower() == "manage" else "head of ")
     + m.group(2).strip()),
    (re.compile(r"\bI(?: am|'m) (?:the |a |an )?((?:[a-z]+ ){0,3}(?:head|director|vp|"
                r"vice president|chief|manager|ceo|coo|cfo|cto|cio)\b[^.,;!?]{0,60})",
                re.IGNORECASE),
     lambda m: m.group(1).strip()),
    (re.compile(r"\bI(?: am|'m) (?:a |an )([a-z ]{0,30}student)\b", re.IGNORECASE),
     lambda m: m.group(1).strip()),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def _first_match(text: str, rules) -> tuple[str, str] | None:
    """(label, sentence) for the first rule label with a matching pattern."""
    for label, patterns in rules:
        for sentence in _sentences(text):
            if any(re.search(p, sentence, re.IGNORECASE) for p in patterns):
                return label, sentence
    return None


def _stated_facts(body: str) -> StatedCompanyFacts:
    employees = vertical = country = company = None
    for sentence in _sentences(body):
        if not _SELF_DESCRIPTION.search(sentence):
            continue
        if employees is None and (m := EMPLOYEES_RE.search(sentence)):
            employees = int(m.group(1).replace(",", ""))
        if vertical is None:
            vertical = next((v for v, p in VERTICAL_RULES
                             if re.search(p, sentence, re.IGNORECASE)), None)
        if company is None and (m := COMPANY_RE.search(sentence)):
            company = m.group(1)
    for m in LOCATION_RE.finditer(body):
        place = m.group(1).lower()
        country = CITY_COUNTRY.get(place) or normalize_country(place)
        if country:
            break
    return StatedCompanyFacts(company_name=company, vertical=vertical, employees=employees,
                              country=country)


def _stated_role(body: str) -> str | None:
    for pattern, render in ROLE_PATTERNS:
        if m := pattern.search(body):
            return render(m)[:120]
    return None


class RulesExtractor:
    name = "rules-v1"

    def extract(self, message: InboundMessage, crm: CrmRecord | None) -> dict:
        text = "\n".join(t for t in (message.subject, message.body) if t)
        language = detect_language(message.body)
        if language not in SUPPORTED_LANGUAGES:
            raise UnsupportedLanguage(language)

        evidence: list[str] = []
        intent_hit = _first_match(text, INTENT_RULES)
        intent = intent_hit[0] if intent_hit else "other"
        problem = None
        no_problem_intents = ("unsubscribe", "auto_reply", "job_seeker", "investor")
        if intent not in no_problem_intents and (
                problem_hit := _first_match(message.body, PROBLEM_RULES)):
            problem = DataProblem(category=problem_hit[0], summary=problem_hit[1][:300])
            evidence.append(problem_hit[1][:300])
        if intent_hit and intent_hit[1] in message.body and intent_hit[1][:300] not in evidence:
            evidence.append(intent_hit[1][:300])

        return Extraction(
            language=language,
            intent=intent,
            buyer_role=_stated_role(message.body),
            data_problem=problem,
            company_facts=_stated_facts(message.body),
            evidence=evidence,
        ).model_dump()
