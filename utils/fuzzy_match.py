from rapidfuzz import process, fuzz

def fuzzy_match(query: str, choices: list, threshold: int = 60) -> str | None:
    """Return the best fuzzy match from choices for the given query."""
    if not choices:
        return None
    result = process.extractOne(query, choices, scorer=fuzz.WRatio)
    if result and result[1] >= threshold:
        return result[0]
    return None

def fuzzy_match_all(query: str, choices: list, threshold: int = 60, limit: int = 5) -> list:
    """Return top fuzzy matches from choices for the given query."""
    results = process.extract(query, choices, scorer=fuzz.WRatio, limit=limit)
    return [r[0] for r in results if r[1] >= threshold]

