"""Speech completeness checks retained from the verified narration pipeline."""
import re
import json
from pathlib import Path

PRONUNCIATIONS = {
    r"\bM3GAN\b": "Megan", r"\bSe7en\b": "Seven", r"\bThir13en\b": "Thirteen", r"\bWALL[-·]E\b": "Wall-E",
    r"\bvs\.?(?=\s)": "versus", r"\bPt\.\s*": "Part ", r"\bDr\.\s": "Doctor ", r"\bMr\.\s": "Mister ", r"\bMrs\.\s": "Missus ",
    r"\bSt\.\s(?=[A-Z])": "Saint ", r"\b(Part|Chapter|Episode)\s+II\b": r"\1 Two", r"\b(Part|Chapter|Episode)\s+III\b": r"\1 Three",
    r"\b(Part|Chapter|Episode)\s+IV\b": r"\1 Four", r"\b(Part|Chapter|Episode)\s+V\b": r"\1 Five", r"&": " and ",
    r"\b(\d{4})[–-](\d{4})\b": r"\1 to \2", r"\b(\d{4})[–-](\d{2})\b": r"\1 to \2",
}

def custom_pronunciations() -> dict[str, str]:
    """Your own respellings from pronunciations.json at the repository root, e.g.
    {"Villeneuve": "Vil-nuv", "Chalamet": "Shala-may"}; whole words, case-sensitive."""
    path = Path(__file__).resolve().parents[1] / "pronunciations.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {rf"\b{re.escape(str(word))}\b": str(spoken) for word, spoken in data.items() if str(word).strip()}


def spoken_form(text: str) -> str:
    """The text as the narrator should say it (respellings for known trouble titles and abbreviations)."""
    for pattern, replacement in {**PRONUNCIATIONS, **custom_pronunciations()}.items():
        text = re.sub(pattern, replacement, text)
    return " ".join(text.split())


_NUMBER_WORDS = dict(zip(
    ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"],
    range(20),
))
_NUMBER_WORDS.update(dict(zip(["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"], range(20, 100, 10))))


def _under_hundred(words: list[str]) -> int | None:
    values = [_NUMBER_WORDS.get(word, int(word) if word.isdigit() else -1) for word in words]
    if len(values) == 1 and 0 <= values[0] < 100:
        return values[0]
    if len(values) == 2 and values[0] in range(20, 100, 10) and 0 < values[1] < 10:
        return sum(values)
    return None


def _under_thousand(words: list[str]) -> int | None:
    if len(words) >= 2 and words[1] == "hundred":
        prefix = _under_hundred(words[:1])
        suffix = _under_hundred(words[2:]) if len(words) > 2 else 0
        if prefix is not None and prefix > 0 and suffix is not None:
            return prefix*100 + suffix
    return _under_hundred(words)


def _number_value(words: list[str]) -> int | None:
    """Parse valid number phrases; adjacent independent numbers never get added."""
    words = [word for word in words if word != "and"]
    if len(words) == 1:
        if words[0].isdigit():
            return int(words[0])
        return {"hundred": 100, "thousand": 1000}.get(words[0], _NUMBER_WORDS.get(words[0]))
    first = _under_hundred(words[:1])
    if first in (18, 19, 20):
        remainder = _under_hundred(words[1:])
        if remainder is not None and 10 <= remainder < 100:
            return first*100 + remainder
    if words.count("thousand") == 1:
        split = words.index("thousand")
        prefix = _under_thousand(words[:split])
        suffix = _under_thousand(words[split+1:]) if split+1 < len(words) else 0
        if prefix is not None and prefix > 0 and suffix is not None:
            return prefix*1000 + suffix
    return _under_thousand(words)


def _speech_tokens(text: str) -> list[str]:
    """Ignore punctuation and tolerate ASR contraction/number formatting changes."""
    text = text.casefold().replace("’", "'")
    for contraction, expanded in {
        "can't": "can not", "cannot": "can not", "won't": "will not", "let's": "let us",
        "i'm": "i am", "it's": "it is", "that's": "that is", "there's": "there is",
        "here's": "here is", "what's": "what is", "who's": "who is", "he's": "he is", "she's": "she is",
    }.items():
        text = re.sub(r"\b" + re.escape(contraction) + r"\b", expanded, text)
    for ending, expanded in (("n't", " not"), ("'re", " are"), ("'ve", " have"), ("'ll", " will"), ("'d", " would")):
        text = re.sub(r"\b(\w+)" + re.escape(ending) + r"\b", r"\1" + expanded, text)
    text = re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", text)
    # Sentence/clause punctuation ends a number phrase. Hyphens still permit
    # ordinary compounds such as twenty-six.
    words = re.findall(r"\w+|[.!?;:,\n]", text)
    tokens = []
    index = 0
    while index < len(words):
        if not re.fullmatch(r"\w+", words[index]):
            index += 1
            continue
        start = index
        numeric = []
        while index < len(words):
            word = words[index]
            if word in _NUMBER_WORDS or word in ("hundred", "thousand") or word.isdigit():
                numeric.append(word)
                index += 1
            elif numeric and word == "and" and index+1 < len(words) and words[index+1] in _NUMBER_WORDS:
                index += 1
            else:
                break
        if numeric:
            # Partition a numeric run into valid phrases, preserving lists such
            # as one two three instead of treating them as the number six.
            while numeric:
                for stop in range(len(numeric), 0, -1):
                    value = _number_value(numeric[:stop])
                    if value is not None:
                        tokens.append(str(value))
                        numeric = numeric[stop:]
                        break
                else:
                    tokens.append(numeric.pop(0))
        else:
            tokens.append(words[start])
            index += 1
    return tokens


def _number_spelling(value: int) -> str:
    small = list(_NUMBER_WORDS)
    if value < 20:
        return small[value]
    if value < 100:
        return small[18+value//10] + (_number_spelling(value % 10) if value % 10 else "")
    if value < 1000:
        return _number_spelling(value//100) + "hundred" + (_number_spelling(value % 100) if value % 100 else "")
    if value < 10000:
        return _number_spelling(value//1000) + "thousand" + (_number_spelling(value % 1000) if value % 1000 else "")
    return str(value)


def _aligned_tokens(planned: list[str], heard: list[str]) -> tuple[set[int], set[int]]:
    """Monotone word alignment with at most a three-token spelling join/split."""
    def spellings(token):
        if not token.isdigit():
            return {token}
        value = int(token)
        forms = {_number_spelling(value)}
        if 1000 <= value <= 2099:
            century, remainder = divmod(value, 100)
            prefix = _number_spelling(century)
            if remainder == 0:
                forms.add(prefix+"hundred")
            elif remainder < 10:
                # Preserve the zero: "twenty one" means 21, not 2001.
                forms.update(prefix+zero+_number_spelling(remainder) for zero in ("oh", "zero"))
            else:
                forms.add(prefix+_number_spelling(remainder))
        return forms

    def spans(tokens):
        result = {}
        for start in range(len(tokens)):
            forms = {""}
            for size in range(1, min(3, len(tokens)-start)+1):
                forms = {prefix+suffix for prefix in forms for suffix in spellings(tokens[start+size-1])}
                result[start, size] = forms
        return result

    left, right = spans(planned), spans(heard)
    scores = [[(0, 0) for _ in range(len(heard)+1)] for _ in range(len(planned)+1)]
    trace = {}

    def update(i, j, score, step):
        if score > scores[i][j]:
            scores[i][j] = score
            trace[(i, j)] = step

    for i in range(len(planned)+1):
        for j in range(len(heard)+1):
            score = scores[i][j]
            if i < len(planned):
                update(i+1, j, score, (i, j, 0, 0))
            if j < len(heard):
                update(i, j+1, score, (i, j, 0, 0))
            for a, b in ((1, 1), (1, 2), (1, 3), (2, 1), (3, 1)):
                if i+a <= len(planned) and j+b <= len(heard) and not left[i, a].isdisjoint(right[j, b]):
                    update(i+a, j+b, (score[0]+a, score[1]+b), (i, j, a, b))
    expected_matches, heard_matches = set(), set()
    position = (len(planned), len(heard))
    while position in trace:
        i, j, a, b = trace[position]
        expected_matches.update(range(i, i+a))
        heard_matches.update(range(j, j+b))
        position = (i, j)
    return expected_matches, heard_matches


def speech_check(expected: str, cues: list[dict]) -> dict:
    """Report completeness evidence without requiring word-perfect ASR.

    The original coverage and boundary requirements are retained. Bounded
    spelling joins tolerate ASR word segmentation; transcript precision rejects
    substantial extra/repeated speech instead of accepting a complete sentence
    merely because it appears somewhere inside a runaway recording.
    """
    # The verifier must compare the pronunciation actually sent to TTS. Keep
    # the written transcript unchanged in diagnostics and captions.
    planned = _speech_tokens(spoken_form(expected))
    transcript = " ".join(cue.get("text", "") for cue in cues)
    heard = _speech_tokens(spoken_form(transcript))
    absent_edge = {"accepted": False, "matched": 0, "required": max(1, (min(8, len(planned))+1)//2),
                   "unmatched_tokens": len(planned)}
    result = {"accepted": False, "coverage": 0.0, "precision": 0.0,
              "reason": "empty_expected" if not planned else "empty_transcript", "heard": transcript,
              "opening": dict(absent_edge), "ending": dict(absent_edge),
              "longest_unmatched_phrase": len(planned)}
    if not planned or not heard:
        return result
    matched, heard_matches = _aligned_tokens(planned, heard)
    result["coverage"] = len(matched)/len(planned)
    result["precision"] = len(heard_matches)/len(heard)
    longest_missing = current_missing = 0
    for index in range(len(planned)):
        current_missing = 0 if index in matched else current_missing+1
        longest_missing = max(longest_missing, current_missing)
    result["longest_unmatched_phrase"] = longest_missing
    edge_allowance = min(2, max(1, len(planned)//8))
    window = min(8, len(planned))
    required = max(1, (window+1)//2)
    for name, indices, omitted in (
        ("opening", range(window), min(matched) if matched else len(planned)),
        ("ending", range(len(planned)-window, len(planned)), len(planned)-1-max(matched) if matched else len(planned)),
    ):
        count = sum(index in matched for index in indices)
        result[name] = {"accepted": omitted <= edge_allowance and count >= required,
                        "matched": count, "required": required, "unmatched_tokens": omitted}
    if result["coverage"] < .72:
        result["reason"] = "coverage"
    elif not result["opening"]["accepted"]:
        result["reason"] = "opening"
    elif not result["ending"]["accepted"]:
        result["reason"] = "ending"
    elif longest_missing >= 6:
        result["reason"] = "missing_or_reordered_phrase"
    elif len(heard) > len(planned)+2 and result["precision"] < .72:
        result["reason"] = "extra_or_repeated_speech"
    else:
        result.update(accepted=True, reason="accepted")
    return result


