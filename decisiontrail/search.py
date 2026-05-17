from __future__ import annotations

from dataclasses import dataclass

from decisiontrail.models import DecisionRecord, filter_records_by_tag, tag_labels
from decisiontrail.review import is_overdue


@dataclass(frozen=True)
class SearchHit:
    record: DecisionRecord
    score: int


def record_search_text(record: DecisionRecord) -> str:
    values = [
        record.id,
        record.title,
        record.status,
        record.owner,
        record.decision_type,
        str(record.metadata.get("context", "") or ""),
        str(record.metadata.get("decision", "") or ""),
        " ".join(str(item) for item in record.rationale),
        " ".join(str(item) for item in record.success_metrics),
        " ".join(tag_labels(record)),
        " ".join(str(item) for item in record.evidence),
        " ".join(str(item) for item in record.metric_updates),
        record.body,
    ]
    return " ".join(values).casefold()


def filter_records(
    records: list[DecisionRecord],
    *,
    status: str | None = None,
    owner: str | None = None,
    tag: str | None = None,
    due: bool = False,
) -> list[DecisionRecord]:
    filtered = records
    if status:
        filtered = [record for record in filtered if record.status == status]
    if owner:
        filtered = [record for record in filtered if record.owner.casefold() == owner.casefold()]
    filtered = filter_records_by_tag(filtered, tag)
    if due:
        filtered = [record for record in filtered if is_overdue(record)]
    return filtered


def search_records(
    records: list[DecisionRecord],
    query: str = "",
    *,
    status: str | None = None,
    owner: str | None = None,
    tag: str | None = None,
    due: bool = False,
    limit: int | None = None,
) -> list[SearchHit]:
    filtered = filter_records(records, status=status, owner=owner, tag=tag, due=due)
    query = query.strip().casefold()
    if not query:
        hits = [SearchHit(record, 0) for record in filtered]
        return hits[:limit] if limit else hits

    terms = [term for term in query.split() if term]
    hits: list[SearchHit] = []
    for record in filtered:
        haystack = record_search_text(record)
        if not all(term in haystack for term in terms):
            continue
        score = 0
        title = record.title.casefold()
        tag_text = " ".join(tag_labels(record)).casefold()
        for term in terms:
            if term in record.id.casefold():
                score += 40
            if term in title:
                score += 20
            if term in tag_text:
                score += 12
            score += haystack.count(term)
        hits.append(SearchHit(record, score))
    hits.sort(key=lambda hit: (-hit.score, hit.record.id))
    return hits[:limit] if limit else hits
