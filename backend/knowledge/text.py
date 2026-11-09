"""Normalização e tokenização de texto em português (sem dependências externas)."""
import re
import unicodedata


def normalize(text: str) -> str:
    """Minúsculas, sem acentos nem pontuação, espaços colapsados."""
    decomposed = unicodedata.normalize("NFKD", str(text).casefold())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def stem(word: str) -> str:
    """Radical leve: junta singular/plural sem tentar ser um stemmer completo."""
    if len(word) > 5 and word.endswith("coes"):
        return word[:-4] + "cao"
    if len(word) > 4 and word.endswith("oes"):
        return word[:-3] + "ao"
    if len(word) > 4 and word.endswith("ais"):
        return word[:-3] + "al"
    if len(word) > 5 and word.endswith(("res", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str, stopwords: set[str] | frozenset[str] = frozenset(), use_stem: bool = True) -> list[str]:
    words = [w for w in normalize(text).split() if w not in stopwords]
    return [stem(w) for w in words] if use_stem else words


def contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    """A sequência 'needle' aparece contígua em 'haystack'?"""
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))
