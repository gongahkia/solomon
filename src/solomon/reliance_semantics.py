# SPDX-License-Identifier: Apache-2.0

"""Reversible normalized analysis and bounded deterministic reliance grammar."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

AUTHORITY_NOUN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:act|code|guidance|reg(?:ulation)?s?\.?|rules?)(?![A-Za-z])", re.IGNORECASE
)
SECTION_TAIL_RE = re.compile(
    r"\s+(?P<number>\d+|[A-Za-z][A-Za-z0-9-]*)\s+(?P<marker>section|s\.?)\s+"
    r"(?P<section>\d+(?:\([A-Za-z0-9]+\))?)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")
TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "depends",
    "distinguishes",
    "follows",
    "for",
    "from",
    "grounded",
    "having",
    "if",
    "in",
    "is",
    "of",
    "on",
    "our",
    "pursuant",
    "relies",
    "rely",
    "subject",
    "that",
    "the",
    "than",
    "this",
    "to",
    "under",
    "uses",
    "we",
    "with",
    "namely",
    "rather",
    "not",
    "rejects",
    "revision",
}
SOURCE_ARTIFACT_RE = re.compile(
    r"\b(?:this\s+|our\s+|the\s+(?:\"?[a-z0-9'’-]+\"?\s+){0,2})"
    r"(?:advice|analysis|assessment|checklist|conclusion|import|memo(?:randum)?|note|opinion|"
    r"position|recommendation|team|template|view|workflow)\b",
    re.IGNORECASE,
)
ACTOR_RE = re.compile(r"\b(?:we|our|this|the\s+firm)\b", re.IGNORECASE)
ATTRIBUTION_RE = re.compile(
    r"\b(?:client|counterparty|court|regulator|witness|opposing\s+counsel|opponent|vendor|claimant)\b"
    r"\s+(?:says|said|rel(?:y|ies|ied)|depends?|follows?|argues?|held|notes?|wrote)",
    re.IGNORECASE,
)
REPORTING_RE = re.compile(r"\b(?:record\s+states|audit\s+notes|training\s+extract)\b", re.IGNORECASE)
NEGATION_RE = re.compile(
    r"\b(?:do|does|did)\s+not\s+(?:rely|depend|follow|use|treat)|\bnot\s+(?:rely|depend|follow|use|treat)|"
    r"\bno\s+longer\s+(?:rel(?:y|ies)|depends?|follows?|uses?)|\brather\s+than\s+(?:rely|depend|follow|use)|"
    r"\bwithout\s+(?:relying|depending|following|using)|\b(?:rejects?|rejected|declines?|declined)\b",
    re.IGNORECASE,
)
HISTORICAL_RE = re.compile(
    r"\b(?:archived\s+(?:assessment|advice|template|source)|obsolete|superseded|earlier\s+draft|once\s+followed|not\s+this\s+advice|"
    r"current\s+advice\s+supersedes|no\s+longer)\b|\bin\s+(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
HYPOTHETICAL_RE = re.compile(
    r"^\s*if\b|\b(?:might|could|would|may)\s+(?:rely|depend|follow|use)\b|\bif\s+counsel\b",
    re.IGNORECASE,
)
BACKGROUND_RE = re.compile(
    r"\b(?:reference\s+table|authorities\s+consulted|status:\s*background|appears\s+in\s+the\s+margin|"
    r"potential\s+basis|heading|no\s+selection|not\s+selected|related\s+material)\b",
    re.IGNORECASE,
)
INDEPENDENT_RE = re.compile(
    r"\b(?:stands|reached|proceed)\s+independently\b|\b(?:does\s+not\s+depend|independent\s+conclusion)\b",
    re.IGNORECASE,
)
UNRESOLVED_RE = re.compile(r"\b(?:may|can)\s+(?:rely|depend|use)\b.*\b(?:or|after\s+further\s+review)\b", re.IGNORECASE)
UNDER_REVIEW_RE = re.compile(r"\bunder\s+review\b", re.IGNORECASE)
QUOTE_RE = re.compile(r'"[^"\n]*"')
CROSS_ANCHOR_RE = re.compile(
    r"\b(?:that\s+(?:authority|rule|deadline|formula|calculation)|for\s+that\s+calculation)\b", re.I
)
CROSS_PREDICATE_RE = re.compile(r"\b(?:supplies|provides|sets|is\s+set\s+by|establishes|governs|uses)\b", re.I)


@dataclass(frozen=True)
class RawInterval:
    """The untouched raw character interval represented by one analysis character."""

    start: int
    end: int


@dataclass(frozen=True)
class NormalizedAnalysis:
    """One canonical matching view with deterministic raw-source reconstruction."""

    raw_text: str
    text: str
    raw_intervals: tuple[RawInterval, ...]

    @property
    def folded_text(self) -> str:
        """Return the case-folded matcher projection of this same analysis view."""

        return self.text.casefold()

    def raw_span(self, start: int, end: int) -> tuple[int, int]:
        """Map an analysis interval to its minimal enclosing raw interval or fail closed."""

        if start < 0 or end <= start or end > len(self.raw_intervals):
            raise ValueError("analysis span is outside the reversible mapping")
        intervals = self.raw_intervals[start:end]
        if any(
            current.start < previous.start or current.end < previous.end
            for previous, current in zip(intervals, intervals[1:], strict=False)
        ):
            raise ValueError("analysis mapping is not monotone")
        return intervals[0].start, intervals[-1].end

    def analysis_span_for_raw(self, start: int, end: int) -> tuple[int, int] | None:
        """Return the smallest analysis interval overlapping a raw interval."""

        if start < 0 or end <= start or end > len(self.raw_text):
            return None
        indexes = [
            index for index, interval in enumerate(self.raw_intervals) if interval.start < end and interval.end > start
        ]
        return (indexes[0], indexes[-1] + 1) if indexes else None


@dataclass(frozen=True)
class RelianceReference:
    """An authority/case reference with both analysis and raw offsets."""

    normalized_id: str
    text: str
    kind: str
    norm_start: int
    norm_end: int
    raw_start: int
    raw_end: int


@dataclass(frozen=True)
class RelianceCandidate:
    """A fail-closed grammar match whose displayed spans are always raw source text."""

    target_id: str
    authority_text: str
    authority_start: int
    authority_end: int
    source_start: int
    source_end: int
    source_text: str
    explanation: str


@dataclass(frozen=True)
class ReliancePattern:
    """A declarative bounded predicate with a local source-actor requirement."""

    identifier: str
    expression: re.Pattern[str]
    requires_actor: bool = True


PATTERNS = (
    ReliancePattern("direct-relies-on", re.compile(r"\brel(?:y|ies)\s+on\b", re.I)),
    ReliancePattern("direct-depends-on", re.compile(r"\bdepends?\s+on\b", re.I)),
    ReliancePattern("direct-required-by", re.compile(r"\brequired\s+by\b", re.I)),
    ReliancePattern("direct-pursuant-to", re.compile(r"\bpursuant\s+to\b", re.I)),
    ReliancePattern("under-operative", re.compile(r"\bunder\b", re.I)),
    ReliancePattern("adoption-approach", re.compile(r"\badopts?\b.*\b(?:approach|calculation|formula)\b", re.I)),
    ReliancePattern("uses-as-rule", re.compile(r"\buses?\b.*\bas\s+(?:its|the)\s+(?:rule|approval\s+rule)\b", re.I)),
    ReliancePattern("treats-controlling", re.compile(r"\btreats?\b.*\bas\s+(?:the\s+)?controlling\b", re.I)),
    ReliancePattern("follows-bounded", re.compile(r"\bfollows?\b.*\b(?:for|only\s+if)\b", re.I)),
    ReliancePattern("grounded-in", re.compile(r"\bgrounded\s+in\b", re.I)),
    ReliancePattern("derives-from", re.compile(r"\bderives?\b.*\bfrom\b", re.I)),
    ReliancePattern("subject-to", re.compile(r"\bsubject\s+to\b", re.I)),
    ReliancePattern("having-regard", re.compile(r"\bhaving\s+regard\s+to\b.*\bwe\s+conclude\b", re.I)),
    ReliancePattern(
        "authority-provides", re.compile(r"\b(?:supplies|provides|sets|establishes)\b", re.I), requires_actor=False
    ),
    ReliancePattern(
        "authority-controls",
        re.compile(r"\b(?:controls?|matters?|is\s+the\s+source\s+of)\b", re.I),
        requires_actor=False,
    ),
    ReliancePattern("replacement-selected", re.compile(r"\breplaces?\b.*\bwith\b", re.I)),
)


def normalize_analysis(raw_text: str) -> NormalizedAnalysis:
    """Normalize matching-only syntax while retaining a raw interval for every output character."""

    units: list[tuple[str, RawInterval]] = []
    quote_map = {"‘": "'", "’": "'", "“": '"', "”": '"'}
    for index, raw_character in enumerate(raw_text):
        interval = RawInterval(index, index + 1)
        normalized = unicodedata.normalize("NFKC", raw_character)
        if raw_character == "§":
            normalized = " section "
        normalized = "".join(quote_map.get(character, character) for character in normalized)
        units.extend((character, interval) for character in normalized)

    text: list[str] = []
    intervals: list[RawInterval] = []
    position = 0
    while position < len(units):
        character, interval = units[position]
        if character.isspace():
            end = position + 1
            while end < len(units) and units[end][0].isspace():
                end += 1
            text.append(" ")
            intervals.append(RawInterval(interval.start, units[end - 1][1].end))
            position = end
            continue
        text.append(character)
        intervals.append(interval)
        position += 1
    return NormalizedAnalysis(raw_text=raw_text, text="".join(text), raw_intervals=tuple(intervals))


def authority_fingerprint(raw_text: str) -> str:
    """Fingerprint an authority only from its raw span and deterministic normalizations."""

    normalized = unicodedata.normalize("NFKC", raw_text).replace("§", " section ").casefold()
    normalized = re.sub(r"\breg\.?(?=\s|$)", "regulation", normalized)
    normalized = re.sub(r"(?<![a-z.])s\.(?=\s|$)", "section", normalized)
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def normalized_authority_references(analysis: NormalizedAnalysis) -> list[RelianceReference]:
    """Parse bounded authority forms from the canonical normalized analysis view."""

    references: list[RelianceReference] = []
    for noun in AUTHORITY_NOUN_RE.finditer(analysis.text):
        tail = SECTION_TAIL_RE.match(analysis.text, noun.end())
        if tail is None:
            continue
        norm_start = _title_start(analysis.text, noun.start())
        norm_end = tail.end()
        try:
            raw_start, raw_end = analysis.raw_span(norm_start, norm_end)
        except ValueError:
            continue
        raw = analysis.raw_text[raw_start:raw_end]
        references.append(
            RelianceReference(
                normalized_id=authority_fingerprint(raw),
                text=raw,
                kind="authority",
                norm_start=norm_start,
                norm_end=norm_end,
                raw_start=raw_start,
                raw_end=raw_end,
            )
        )
    return _deduplicate_references(references)


def supplement_references(
    analysis: NormalizedAnalysis,
    references: Iterable[tuple[str, str, str, int | None, int | None]],
) -> list[RelianceReference]:
    """Add legacy-only case/declared-alias forms without replacing normalized authority forms."""

    combined = normalized_authority_references(analysis)
    for normalized_id, text, kind, raw_start, raw_end in references:
        if raw_start is None or raw_end is None:
            continue
        analysis_span = analysis.analysis_span_for_raw(raw_start, raw_end)
        if analysis_span is None:
            continue
        candidate = RelianceReference(
            normalized_id=normalized_id,
            text=text,
            kind=kind,
            norm_start=analysis_span[0],
            norm_end=analysis_span[1],
            raw_start=raw_start,
            raw_end=raw_end,
        )
        if any(_raw_overlap(candidate, existing) for existing in combined):
            continue
        combined.append(candidate)
    return _deduplicate_references(combined)


def analyze_reliance(
    raw_text: str,
    *,
    fallback_references: Iterable[tuple[str, str, str, int | None, int | None]] = (),
    registered_authority_ids: Sequence[str] | None = None,
) -> tuple[NormalizedAnalysis, list[RelianceReference], list[RelianceCandidate]]:
    """Apply the one bounded grammar and return only reversible raw-source candidates."""

    analysis = normalize_analysis(raw_text)
    references = supplement_references(analysis, fallback_references)
    allowed = set(registered_authority_ids) if registered_authority_ids is not None else None
    candidate_references = [
        reference for reference in references if allowed is None or reference.normalized_id in allowed
    ]
    candidates = _same_sentence_candidates(analysis, candidate_references)
    candidates.extend(_cross_sentence_candidates(analysis, candidate_references))
    return analysis, references, _deduplicate_candidates(candidates)


def _title_start(text: str, noun_start: int) -> int:
    prefix = text[:noun_start]
    words = list(WORD_RE.finditer(prefix))
    start = noun_start
    consumed = 0
    while words and consumed < 4:
        word = words.pop()
        between = prefix[word.end() : start]
        if not between.isspace() or word.group(0).casefold() in TITLE_STOP_WORDS:
            break
        start = word.start()
        consumed += 1
    return start


def _same_sentence_candidates(
    analysis: NormalizedAnalysis, references: list[RelianceReference]
) -> list[RelianceCandidate]:
    candidates: list[RelianceCandidate] = []
    for sentence_start, sentence_end in _sentence_spans(analysis.text):
        sentence = analysis.text[sentence_start:sentence_end]
        local_references = [
            reference
            for reference in references
            if reference.norm_start >= sentence_start and reference.norm_end <= sentence_end
        ]
        if not local_references:
            continue
        guards = _guard_results(sentence)
        if any(guards.values()):
            continue
        actor = _actor_cue(sentence)
        for pattern in PATTERNS:
            match = pattern.expression.search(sentence)
            if match is None or (pattern.requires_actor and actor is None):
                continue
            if pattern.identifier == "under-operative" and not _under_is_operational(sentence, actor):
                continue
            for reference in local_references:
                if pattern.identifier in {"authority-provides", "authority-controls"} and reference.norm_start > (
                    sentence_start + match.start()
                ):
                    continue
                if _reference_has_local_exclusion(analysis.text, reference):
                    continue
                if _association_distance(match, reference, sentence_start) > 240:
                    continue
                candidate = _candidate_from_window(
                    analysis,
                    reference,
                    sentence_start,
                    sentence_end,
                    pattern.identifier,
                    actor or "operative-source-artifact",
                    match.group(0),
                    guards,
                    "same-sentence",
                )
                if candidate is not None:
                    candidates.append(candidate)
            break
    return candidates


def _cross_sentence_candidates(
    analysis: NormalizedAnalysis, references: list[RelianceReference]
) -> list[RelianceCandidate]:
    candidates: list[RelianceCandidate] = []
    sentences = _sentence_spans(analysis.text)
    for (previous_start, previous_end), (current_start, current_end) in zip(sentences, sentences[1:], strict=False):
        if current_end - previous_start > 480:
            continue
        previous = analysis.text[previous_start:previous_end]
        current = analysis.text[current_start:current_end]
        if _actor_cue(previous) is None or re.search(r"\badopts?\b", previous, re.I) is None:
            continue
        anchor = CROSS_ANCHOR_RE.search(current)
        predicate = CROSS_PREDICATE_RE.search(current)
        guards = _guard_results(f"{previous} {current}")
        if anchor is None or predicate is None or any(guards.values()):
            continue
        for reference in references:
            if reference.norm_start < previous_start or reference.norm_end > current_end:
                continue
            candidate = _candidate_from_window(
                analysis,
                reference,
                previous_start,
                current_end,
                "cross-sentence-adoption",
                _actor_cue(previous) or "source-artifact",
                predicate.group(0),
                guards,
                "previous+current",
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for index, character in enumerate(text):
        if character not in ".!?":
            continue
        next_character = text[index + 1] if index + 1 < len(text) else ""
        prior_word = text[max(0, index - 10) : index].casefold().rsplit(" ", 1)[-1]
        if character == "." and prior_word in {"fn", "reg", "s", "v"}:
            continue
        if next_character and not next_character.isspace():
            continue
        _append_sentence_span(spans, text, start, index + 1)
        start = index + 1
    _append_sentence_span(spans, text, start, len(text))
    return spans


def _append_sentence_span(spans: list[tuple[int, int]], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end))


def _actor_cue(sentence: str) -> str | None:
    artifact = SOURCE_ARTIFACT_RE.search(sentence)
    direct = ACTOR_RE.search(sentence)
    match = artifact or direct
    return match.group(0) if match is not None else None


def _under_is_operational(sentence: str, actor: str | None) -> bool:
    if actor is None or UNDER_REVIEW_RE.search(sentence):
        return False
    return bool(
        re.search(r"\b(?:we|our|approve|send|follow|proceed|conclude|uses?|depends?|rel(?:y|ies))\b", sentence, re.I)
    )


def _guard_results(sentence: str) -> dict[str, bool]:
    folded = sentence.casefold()
    predicate_in_quote = any(
        re.search(r"\b(?:rel(?:y|ies)|depends?|follows?|uses?|required|pursuant|adopts?|controls?)\b", quote, re.I)
        for quote in QUOTE_RE.findall(sentence)
    )
    return {
        "attribution": bool(ATTRIBUTION_RE.search(sentence) or REPORTING_RE.search(sentence)),
        "quotation": predicate_in_quote,
        "negation": bool(NEGATION_RE.search(sentence)),
        "historical": bool(HISTORICAL_RE.search(sentence)),
        "hypothetical": bool(HYPOTHETICAL_RE.search(sentence)),
        "background": bool(BACKGROUND_RE.search(sentence)),
        "independent": bool(INDEPENDENT_RE.search(sentence)),
        "unresolved": bool(UNRESOLVED_RE.search(sentence)),
        "instruction": bool(re.search(r"\bdraft\s+a\s+note\b", sentence, re.I)),
        "under_review": bool(UNDER_REVIEW_RE.search(sentence)),
        "empty": not bool(folded.strip()),
    }


def _association_distance(match: re.Match[str], reference: RelianceReference, sentence_start: int) -> int:
    reference_start = reference.norm_start - sentence_start
    reference_end = reference.norm_end - sentence_start
    if match.start() <= reference_start <= match.end() or reference_start <= match.start() <= reference_end:
        return 0
    return min(abs(reference_start - match.end()), abs(match.start() - reference_end))


def _reference_has_local_exclusion(text: str, reference: RelianceReference) -> bool:
    """Reject only an authority locally introduced as the excluded alternative."""

    prefix = text[max(0, reference.norm_start - 32) : reference.norm_start]
    return bool(re.search(r"\b(?:not|rather\s+than)\s*$", prefix, re.I))


def _candidate_from_window(
    analysis: NormalizedAnalysis,
    reference: RelianceReference,
    norm_start: int,
    norm_end: int,
    pattern: str,
    actor: str,
    predicate: str,
    guards: dict[str, bool],
    window: str,
) -> RelianceCandidate | None:
    try:
        raw_start, raw_end = analysis.raw_span(norm_start, norm_end)
    except ValueError:
        return None
    raw_start, raw_end = _trim_raw_span(analysis.raw_text, raw_start, raw_end)
    if raw_start >= raw_end:
        return None
    guard_text = ",".join(f"{name}:{'hit' if value else 'clear'}" for name, value in sorted(guards.items()))
    return RelianceCandidate(
        target_id=reference.normalized_id,
        authority_text=reference.text,
        authority_start=reference.raw_start,
        authority_end=reference.raw_end,
        source_start=raw_start,
        source_end=raw_end,
        source_text=analysis.raw_text[raw_start:raw_end],
        explanation=(
            f"normalized-analysis pattern={pattern}; actor={actor}; predicate={predicate}; "
            f"authority={reference.normalized_id}; window={window}; normalized_window={norm_start}:{norm_end}; "
            f"raw_evidence={raw_start}:{raw_end}; raw_authority={reference.raw_start}:{reference.raw_end}; "
            f"guards={guard_text}"
        ),
    )


def _trim_raw_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _deduplicate_references(references: list[RelianceReference]) -> list[RelianceReference]:
    deduplicated: dict[tuple[str, int, int], RelianceReference] = {}
    for reference in references:
        deduplicated.setdefault((reference.normalized_id, reference.raw_start, reference.raw_end), reference)
    return sorted(
        deduplicated.values(), key=lambda reference: (reference.raw_start, reference.raw_end, reference.normalized_id)
    )


def _deduplicate_candidates(candidates: list[RelianceCandidate]) -> list[RelianceCandidate]:
    deduplicated: dict[tuple[str, int, int], RelianceCandidate] = {}
    for candidate in candidates:
        key = (candidate.target_id, candidate.authority_start, candidate.authority_end)
        current = deduplicated.get(key)
        if current is None or "cross-sentence-adoption" in candidate.explanation:
            deduplicated[key] = candidate
    return sorted(deduplicated.values(), key=lambda candidate: (candidate.authority_start, candidate.target_id))


def _raw_overlap(left: RelianceReference, right: RelianceReference) -> bool:
    return left.raw_start < right.raw_end and left.raw_end > right.raw_start
