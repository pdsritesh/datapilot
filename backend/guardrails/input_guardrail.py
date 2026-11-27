"""
Step 1: Input Guardrail — runs BEFORE any LLM call, at zero cost.

Layers (first match blocks):
  1. SQL-syntax injection (obfuscation-resistant: leetspeak, letter-spacing)
  2. Jailbreak / prompt-injection phrases
  3. Plain-English destructive/write intent ("wipe all orders")
  4. Non-data chit-chat, off-topic requests
  5. Gibberish (no pronounceable word)
  6. Relevance gate: query must mention a domain term (demo DB) or a word from
     the connected database's own table/column names, or a generic data-question word

Normalization pipeline:
  _leet_normalize()                  -> "d3l3t3" becomes "delete", spacing kept
  _strip_word_internal_separators()  -> "d.e.l.e.t.e" becomes "delete", real spaces kept
  _collapse()                        -> spaces removed too, only for adjacent-keyword
                                        SQL patterns such as "droptable"

This is a cheap first filter, not the only defense: the SQL validator, the
read-only executor and the generator's refusal rule all sit behind it.
"""
import re

MAX_QUERY_LENGTH = 300

# --- Leetspeak / obfuscation normalization -------------------------------

LEET_SUBSTITUTIONS = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
}


def _leet_normalize(text: str) -> str:
    """Replace common leetspeak substitutions, keeping spacing intact."""
    return "".join(LEET_SUBSTITUTIONS.get(ch, ch) for ch in text)


def _strip_word_internal_separators(text: str) -> str:
    """
    Remove periods, hyphens, underscores and asterisks used to space out
    letters WITHIN a word ("d.e.l.e.t.e", "d-r-o-p"), while leaving real
    whitespace between actual words untouched, so phrase-level checks that
    rely on \\b word boundaries still work.
    """
    return re.sub(r"[._\-*]", "", text)


def _collapse(text: str) -> str:
    """Strip every non-alphanumeric character, including spaces (adjacent-keyword checks only)."""
    return re.sub(r"[^a-z0-9]", "", text)


# --- SQL-syntax injection patterns (checked against the collapsed form) --

COLLAPSED_INJECTION_PATTERNS = [
    r"ignore(all)?(previous|above)instructions",
    r"droptable",
    r"deletefrom",
    r"insertinto",
    r"update\w*set",
    r"altertable",
    r"truncate",
    r"youarenow",
    r"systemprompt",
    r"reveal(your|the)?(system)?(prompt|instructions)",
    r"debugmode",
    r"bypass(validation|thevalidator|thesafety|theguardrail)",
    r"actasadatabaseadministrator",
    r"databaseadministrator",
]

# --- Jailbreak / authority-framing phrases (spacing kept) -----------------

PHRASE_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above)\s+instructions",
    r"you\s+are\s+now\b",
    r"system\s*prompt",
    r"reveal\s+(your|the)\s+(system\s+)?(prompt|instructions)",
    r"debug\s*mode",
    r"bypass\s+(the\s+)?(validation|validator|safety|guardrail)",
    r"for\s+testing\s+purposes",
    r"translate\s+the\s+following",
    r"\bact\s+as\b",
    r"role\s*play\s+as",
    r"pretend\s+(that\s+)?(the\s+)?(guardrail|validation|safety)",
    r"i'?m\s+authoriz(ing|ed)",
    r"as\s+the\s+(database\s+)?admin(istrator)?",
    r"database\s+admin(istrator)?",
]

# --- Plain-English destructive / write intent, independent of SQL syntax ---

DESTRUCTIVE_INTENT_PATTERNS = [
    r"\b(wipe|delete|remove|erase|clear|purge|destroy|reset|empty)\b.{0,30}\b"
    r"(database|db|table|tables|customer|customers|order|orders|record|records|"
    r"row|rows|data|everything|entry|entries)\b",
    r"\b(get\s+rid\s+of|clean\s+up|clear\s+out)\b.{0,30}\b"
    r"(database|db|table|tables|customer|customers|order|orders|record|records|"
    r"row|rows|data|everything)\b",
    r"\b(add|insert|create)\b.{0,30}\b(a\s+)?(new\s+)?"
    r"(customer|order|record|row|entry)\b",
    r"\b(change|update|modify|edit|set)\b.{0,40}\b"
    r"(city|name|amount|email|address|record|value)\b.{0,20}\bto\b",
]

NON_DATA_PATTERNS = [
    r"^(hi|hello|hey|thanks|thank you)\W*$",
]

# --- Off-topic / out-of-scope detection ---------------------------------

OFF_TOPIC_PATTERNS = [
    r"\bweather\b",
    r"\bjoke\b",
    r"\bpoem\b",
    r"\brecipe\b",
    r"\bessay\b",
    r"\bwrite\s+(me\s+)?(a|an)\s+\d*\s*(word\s+)?(essay|article|story|poem|blog)",
    r"\btranslate\b.{0,20}\b(to|into)\b",
    r"\bwhat\s+is\s+the\s+capital\s+of\b",
    r"\bwho\s+(won|is)\s+the\s+(election|president|prime\s+minister)\b",
]

# Terms that signal a question is plausibly ABOUT the demo dataset
# (mall purchase data — customers and orders).
DOMAIN_HINT_TERMS = [
    "customer", "customers", "order", "orders", "purchase", "purchases",
    "revenue", "sales", "spend", "spent", "amount", "city", "category",
    "categories", "item", "product", "signup", "membership", "date",
    "table", "database", "record", "row", "column", "data", "query",
]

# Generic words that signal a data question even when no domain term appears
DATA_INTENT_WORDS = {
    "show", "list", "get", "find", "give", "display", "count", "total", "sum",
    "average", "avg", "mean", "max", "min", "top", "bottom", "most", "least",
    "highest", "lowest", "best", "worst", "how", "many", "much", "which", "what",
    "who", "when", "where", "per", "each", "number", "between", "latest",
    "recent", "recently", "oldest", "newest", "biggest", "largest", "smallest",
}


def _looks_like_gibberish(text: str) -> bool:
    """True if no word in the query looks like a pronounceable word."""
    words = re.findall(r"[a-z]{2,}", text.lower())
    if not words:
        return True

    def bad(w: str) -> bool:
        if not re.search(r"[aeiouy]", w):                  # "sdfg"
            return True
        if re.search(r"[^aeiouy]{5,}", w):                 # 5+ consonants in a row
            return True
        if len(w) >= 4 and len(set(w)) <= 2:               # "aaaa", "ababab"
            return True
        return False

    return all(bad(w) for w in words)


def _matches_vocab(tokens: set, vocab) -> bool:
    """Token match with naive plural handling (orders ~ order)."""
    for t in tokens:
        if t in vocab or t.rstrip("s") in vocab or (t + "s") in vocab:
            return True
    return False


class GuardrailResult:
    def __init__(self, passed: bool, reason: str = "", category: str = None):
        self.passed = passed
        self.reason = reason
        # category lets callers (pipeline logging, the /tracing page) tell
        # WHICH rule fired, not just that something did.
        self.category = category

    def __repr__(self):
        return f"GuardrailResult(passed={self.passed}, reason='{self.reason}', category={self.category!r})"


def check_input(query: str, connected_db: bool = False, extra_vocab: set = None) -> GuardrailResult:
    """
    connected_db: True when the session is connected to a user's own PostgreSQL
                  database. The demo vocabulary (DOMAIN_HINT_TERMS) doesn't apply
                  there, so the relevance gate uses extra_vocab instead.
    extra_vocab:  lowercase words from the connected database's table and column
                  names (pipeline.py builds it). If empty/None for a connected DB,
                  the relevance gate is skipped, because there's nothing to judge by.
    """
    if not query or not query.strip():
        return GuardrailResult(False, "Empty query", category="empty")

    if len(query) > MAX_QUERY_LENGTH:
        return GuardrailResult(False, f"Query too long (max {MAX_QUERY_LENGTH} chars)", category="too_long")

    lowered = query.lower()
    leet = _leet_normalize(lowered)                        # digits/symbols normalized, spacing kept
    deobfuscated = _strip_word_internal_separators(leet)   # letter-spacing removed, real spaces kept
    collapsed = _collapse(deobfuscated)                    # nothing but a-z0-9, for adjacent-keyword tricks

    # 1. SQL-syntax injection, including obfuscated/spaced-out variants
    for pattern in COLLAPSED_INJECTION_PATTERNS:
        if re.search(pattern, collapsed):
            return GuardrailResult(False, "Query blocked: potentially unsafe content detected", category="injection")

    # 2. Jailbreak / prompt-injection framing
    for pattern in PHRASE_INJECTION_PATTERNS:
        if re.search(pattern, deobfuscated):
            return GuardrailResult(False, "Query blocked: potentially unsafe content detected", category="jailbreak")

    # 3. Plain-English destructive/write intent
    for pattern in DESTRUCTIVE_INTENT_PATTERNS:
        if re.search(pattern, deobfuscated):
            return GuardrailResult(
                False,
                "Query blocked: this looks like a request to modify or delete data, which isn't supported",
                category="destructive_intent",
            )

    for pattern in NON_DATA_PATTERNS:
        if re.match(pattern, lowered.strip()):
            return GuardrailResult(False, "This doesn't look like a data question", category="non_data")

    # 4. Off-topic: only blocks when an off-topic signal fires AND no domain
    # term is present, so "how did weather affect customer purchases" still passes.
    has_off_topic_signal = any(re.search(p, deobfuscated) for p in OFF_TOPIC_PATTERNS)
    has_domain_hint = any(term in lowered for term in DOMAIN_HINT_TERMS)
    if has_off_topic_signal and not has_domain_hint:
        return GuardrailResult(False, "This doesn't look like a question about the mall purchase data", category="off_topic")

    # 5. Gibberish — nothing in the query is a pronounceable word
    if _looks_like_gibberish(lowered):
        return GuardrailResult(False, "I couldn't understand that. Try asking a question about your data.", category="gibberish")

    # 6. Relevance gate. Demo DB uses the mall vocabulary; a connected DB uses
    # its own table/column words (extra_vocab).
    tokens = set(re.findall(r"[a-z]+", lowered))
    if connected_db:
        vocab = DATA_INTENT_WORDS | set(extra_vocab or ())
        gate_applies = bool(extra_vocab)
        message = "That doesn't look related to your database. Try asking about its tables or columns."
    else:
        vocab = set(DOMAIN_HINT_TERMS) | DATA_INTENT_WORDS
        gate_applies = True
        message = "That doesn't look related to the mall purchase data. Try asking about customers, orders, revenue or cities."

    if gate_applies and not _matches_vocab(tokens, vocab):
        return GuardrailResult(False, message, category="unrelated")

    return GuardrailResult(True)


if __name__ == "__main__":
    for q in ["how many customers are there?", "erf werf", "4rgf 4trg 4", "drop table customers"]:
        print(repr(q), "->", check_input(q))