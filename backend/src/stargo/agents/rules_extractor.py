"""Agent A, rules-only fallback: keyword extraction used when no LLM key is set.

It reads English, Dutch, German and Hebrew keywords. Anything else is reported
as unsupported so the lead lands in `needs review` instead of being judged on
words it cannot read.
"""

import re

from stargo.agents.schemas import (
    INTEREST_INTENTS,
    DataProblem,
    Extraction,
    Intent,
    StatedCompanyFacts,
)
from stargo.domain.models import CrmRecord, InboundMessage
from stargo.domain.normalize import normalize_country

SUPPORTED_LANGUAGES = frozenset({"en", "nl", "de", "he"})


class UnsupportedLanguage(Exception):
    pass


class LowConfidence(Exception):
    """The keyword lexicon is too thin to trust a negative result in this language."""


_STOPWORDS = {
    "en": {"the", "and", "to", "we", "our", "is", "a", "of", "for", "you", "i", "in", "with",
           "can", "this", "please", "would", "us", "my", "your", "are", "me", "thanks", "more",
           "it", "on", "be", "will", "not", "have", "any", "send", "tell", "stop"},
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
        # Short plain-ASCII text with no stopword hit ("Interesting!") is most likely English.
        return "en" if words and text.isascii() else "unknown"
    return "en" if scores["en"] == best else max(scores, key=lambda k: scores[k])


INTENT_RULES: list[tuple[Intent, list[str]]] = [
    ("unsubscribe", [r"\bunsubscribe\b", r"remove me from", r"\bopt[- ]?out\b",
                     r"stop (emailing|contacting|sending)", r"take me off",
                     r"(don't|do not) (contact|email|message|write to) me",
                     r"no (more|further) (e-?mails|messages)", r"uitschrijven",
                     r"\bafmelden\b", r"\babmelden\b", r"austragen", r"להסיר אותי", r"הסירו",
                     r"תסירו אותי"]),
    ("auto_reply", [r"out of (the )?office", r"automatic reply", r"auto[- ]?reply",
                    r"limited access to (my )?e-?mail", r"no access to (my )?e-?mail",
                    r"away from (the )?office", r"^\s*ooo\b",
                    r"\bon (annual |parental |sick )?leave\b",
                    r"(will|I'll) (be )?(return|back)(ing)? on\b",
                    r"message will not be forwarded",
                    r"\bafwezig\b", r"abwesenheit", r"nicht im büro", r"מחוץ למשרד"]),
    ("not_interested", [r"not interested", r"no interest",
                        r"already (have|use) a (solution|tool|vendor|provider)",
                        r"not a priority", r"no need for", r"geen interesse",
                        r"kein interesse", r"לא מעוניינ"]),
    ("job_seeker", [r"\binternship\b", r"\bintern\b", r"\bjob\b", r"open (position|role)s?",
                    r"\bmy (cv|resume)\b", r"\bstudent\b", r"\bvacanc", r"\bare you hiring\b",
                    r"\bapply(ing)? for\b", r"\bthesis\b", r"\bdissertation\b",
                    r"\b(university|school) (project|assignment)\b"]),
    ("investor", [r"funding round", r"next round", r"\binvest(s|ed|or|ors|ment|ing)?\b",
                  r"\bvaluation\b", r"\bportfolio compan", r"seed extension", r"series [a-d]\b"]),
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
                                r"audit\w* (freight |carrier )?invoices", r"contracted rates",
                                r"overcharg", r"freight audit"]),
    ("trade_document_checking", [r"letters? of credit", r"trade documents?",
                                 r"documentary (credit|collection)", r"before funds"]),
    ("document_extraction", [r"bills? of lading", r"air ?waybills?", r"\bawbs?\b", r"re-?key",
                             r"manual(ly)? (data |booking )?entry",
                             r"booking confirmations", r"from pdfs?", r"import declarations?",
                             r"customs (paperwork|declarations?|documents?)", r"packing lists?",
                             r"document (automation|extraction)", r"data entry",
                             r"handmatig", r"vrachtbrie", r"manuell", r"frachtbrie",
                             r"הקלדה ידנית", r"מקלידים", r"שטרי מטען"]),
    ("rate_quoting", [r"rate requests?", r"spot (rate|quote)s?", r"\bquot(e|es|ing|ation)\b",
                      r"\brfqs?\b", r"rate cards?", r"\btariffs?\b", r"\btender",
                      r"הצעות מחיר", r"מתמחר", r"\bofferte", r"\bangebot", r"\btarie"]),
]

_SELF_DESCRIPTION = re.compile(
    r"\b(we are|we're|i own|i run|i head|our company|i work (at|for)|i am|i'm|we sell|we build"
    r"|we make|we develop|we provide|wir sind|ich bin|wij zijn|we zijn|ik ben)\b"
    r"|אני|אנחנו", re.IGNORECASE)

VERTICAL_RULES = [
    ("customs-broker", r"customs broker(age)?|zollagent|douane-?expediteur|עמילות מכס"),
    ("freight-forwarder", r"freight forward(er|ing)|\bforwarder\b|\bspedition\b|\bexpediteur\b"
                          r"|שילוח"),
    ("3pl", r"\b3pl\b|third[- ]party logistics"),
    ("air-cargo", r"air cargo"),
    ("ground-handling", r"ground handl"),
    ("trucking", r"\btrucking\b|\bhaulage\b|\bhaulier\b"),
    ("trade-finance", r"trade financ|\bbank\b"),
    ("carrier", r"\bshipping line\b|\bwe are a carrier\b"),
    ("software-vendor", r"\bsoftware\b"),
]

CITY_COUNTRY = {
    "haifa": "IL", "tel aviv": "IL", "ashdod": "IL", "jerusalem": "IL", "eilat": "IL",
    "חיפה": "IL", "תל אביב": "IL", "אשדוד": "IL", "ירושלים": "IL", "אילת": "IL",
    "rotterdam": "NL", "amsterdam": "NL", "antwerp": "BE", "antwerpen": "BE",
    "brussels": "BE", "brussel": "BE",
    "hamburg": "DE", "bremen": "DE", "berlin": "DE", "munich": "DE", "münchen": "DE",
    "frankfurt": "DE", "vienna": "AT", "wien": "AT", "zurich": "CH", "zürich": "CH",
    "basel": "CH",
    "london": "GB", "manchester": "GB", "felixstowe": "GB", "southampton": "GB",
    "liverpool": "GB", "birmingham": "GB", "leeds": "GB", "bristol": "GB", "glasgow": "GB",
    "edinburgh": "GB", "dover": "GB", "immingham": "GB",
    "duisburg": "DE", "cologne": "DE", "köln": "DE", "stuttgart": "DE", "düsseldorf": "DE",
    "utrecht": "NL", "eindhoven": "NL", "venlo": "NL", "ghent": "BE", "gent": "BE",
    "liège": "BE", "malmö": "SE", "bergen": "NO", "tampere": "FI", "geneva": "CH",
    "salzburg": "AT", "petah tikva": "IL", "netanya": "IL", "beer sheva": "IL",
    "copenhagen": "DK", "aarhus": "DK", "gothenburg": "SE", "stockholm": "SE", "oslo": "NO",
    "helsinki": "FI", "singapore": "SG",
    "new york": "US", "chicago": "US", "dallas": "US", "los angeles": "US", "miami": "US",
    "houston": "US", "atlanta": "US", "memphis": "US", "louisville": "US",
    "savannah": "US", "seattle": "US", "newark": "US", "long beach": "US", "denver": "US",
    "boston": "US", "san francisco": "US", "philadelphia": "US", "detroit": "US",
}

EMPLOYEES_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+)(?:[- ](?:person|people|employee|staff|strong)\b"
    r"| (?:employees|people|staff|mitarbeiter\w*|medewerkers|werknemers|עובדים))",
    re.IGNORECASE)
LOCATION_RE = re.compile(r"\b(?:in|based in|from|out of) ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)"
                         r"|(?:^|\s)ב([\u05D0-\u05EA]+(?: [\u05D0-\u05EA]+)?)")
COMPANY_RE = re.compile(r"\b(?:at|for) ([A-Z][\w&-]+(?: [A-Z][\w&-]+){0,2})")

# Role words in Dutch, German and Hebrew, mapped to English for the seniority rules.
ROLE_WORDS = {
    "leiter": "head", "leiterin": "head", "geschäftsführer": "managing director",
    "geschäftsführerin": "managing director", "inhaber": "owner", "inhaberin": "owner",
    "directeur": "director", "eigenaar": "owner", "hoofd": "head",
    "הבעלים": "owner", "בעלים": "owner", "מנכ\"ל": "ceo", "מנכ״ל": "ceo",
    "סמנכ\"ל": "vp", "סמנכ״ל": "vp", "מנהל": "manager", "מנהלת": "manager",
}


def _translate_role(text: str) -> str:
    return " ".join(ROLE_WORDS.get(w.lower(), w) for w in text.split())


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
    (re.compile(r"\b(?:ich bin|ik ben) (?:der |die |de |een )?([^\s.,;!?]+(?: [^\s.,;!?]+)?)",
                re.IGNORECASE),
     lambda m: _translate_role(m.group(1))),
    (re.compile(r"אני (הבעלים|בעלים|מנכ[\"״]ל|סמנכ[\"״]ל|מנהלת?)(?: ([\u05D0-\u05EA]+))?"),
     lambda m: _translate_role(m.group(1))),
    # Last resort: "I'm a pricing analyst", "I'm the operations lead".
    (re.compile(r"\bI(?: am|'m) (?:the |a |an )([a-z][a-z -]{2,40}?)(?: at\b| here\b| for\b"
                r"|[.,;!?]|$)", re.IGNORECASE),
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
        place = (m.group(1) or m.group(2)).lower()
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

        # Outside English the lexicon is small: a missing problem or intent is more likely
        # a gap in our keywords than in the message, so defer to a human instead.
        if language != "en" and intent in ("other", *INTEREST_INTENTS) and (
                intent == "other" or problem is None):
            raise LowConfidence(language)

        return Extraction(
            language=language,
            intent=intent,
            buyer_role=_stated_role(message.body),
            data_problem=problem,
            company_facts=_stated_facts(message.body),
            evidence=evidence,
        ).model_dump()
