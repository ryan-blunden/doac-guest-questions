#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "transcripts"
QUESTIONS_PATH = ROOT / "questions.json"

QUESTION_START_PATTERN = re.compile(
    r"(?:what|how|why|when|where|who|which|if\s+you|do\s+you|does|did|is\s+there|are\s+you|can\s+you|could\s+you|would\s+you|will\s+you|what's|whats)\b",
    re.IGNORECASE,
)

ANCHOR_PATTERNS = [
    re.compile(r"question\s+left\s+for\s+you(?:\s+(?:is|was))?", re.IGNORECASE),
    re.compile(r"last gu(?:e)?s[st]\s+leaves?\s+(?:a\s+)?question\s+for\s+the\s+next\s+gu(?:e)?s[st]", re.IGNORECASE),
    re.compile(r"question\s+for\s+the\s+next\s+guest", re.IGNORECASE),
    re.compile(r"leaves?\s+(?:a\s+)?question(?:\s+for\s+(?:you|the\s+next\s+guest))?", re.IGNORECASE),
    re.compile(r"closing\s+tradition(?:\s+on\s+this\s+podcast)?", re.IGNORECASE),
    re.compile(r"tradition(?:\s+on\s+this\s+podcast)?", re.IGNORECASE),
    re.compile(r"the\s+last\s+guest(?:s|')?\s+question", re.IGNORECASE),
]

FALLBACK_SPLIT_PATTERNS = [
    re.compile(r"(?:youtube have this new crazy algorithm|that was fantastic|thank you so much)", re.IGNORECASE),
    re.compile(r"(?:if anyone wants to go and read more|where do they go)", re.IGNORECASE),
]


@dataclass
class Episode:
    video_id: str
    url: str
    title: str
    description: str | None
    transcript: str
    question: str | None
    extraction_method: str


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80] or "episode"


def transcript_path_for_video_id(video_id: str) -> Path | None:
    matches = sorted(TRANSCRIPTS_DIR.glob(f"*-{video_id}.md"))
    return matches[0] if matches else None


def parse_front_matter_value(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "":
        return None
    if raw[0] in {'"', "["} or raw in {"null", "true", "false"}:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return raw


def read_transcript_markdown(path: Path) -> Episode:
    text = path.read_text()
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise RuntimeError(f"Invalid transcript front matter in {path}")

    closing_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise RuntimeError(f"Incomplete transcript front matter in {path}")

    data: dict[str, str | None] = {}
    for line in lines[1:closing_index]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = parse_front_matter_value(value)

    video_id = data.get("video_id")
    title = data.get("title")
    url = data.get("url")
    extraction_method = data.get("question_extraction") or "existing"
    if not isinstance(video_id, str) or not isinstance(title, str) or not isinstance(url, str):
        raise RuntimeError(f"Missing required front matter fields in {path}")

    description = data.get("description")
    question = data.get("question")

    return Episode(
        video_id=video_id,
        url=url,
        title=title,
        description=description if isinstance(description, str) else None,
        transcript="\n".join(lines[closing_index + 1 :]).strip(),
        question=question if isinstance(question, str) else None,
        extraction_method=extraction_method if isinstance(extraction_method, str) else "existing",
    )


def write_transcript_markdown(episode: Episode) -> None:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    slug = slugify(episode.title)
    path = TRANSCRIPTS_DIR / f"{slug}-{episode.video_id}.md"
    front_matter = [
        "---",
        f'title: "{episode.title.replace(chr(34), chr(92) + chr(34))}"',
        f"url: {episode.url}",
        f"video_id: {episode.video_id}",
    ]
    if episode.description:
        escaped_description = json.dumps(episode.description, ensure_ascii=False)
        front_matter.append(f"description: {escaped_description}")
    if episode.question:
        escaped_question = episode.question.replace(chr(34), chr(92) + chr(34))
        front_matter.append(f'question: "{escaped_question}"')
    front_matter.extend(
        [
            f"question_extraction: {episode.extraction_method}",
            "---",
            "",
            episode.transcript.strip(),
            "",
        ]
    )
    path.write_text("\n".join(front_matter))


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_sentences(text: str) -> Iterable[str]:
    return re.split(r"(?<=[?.!])\s+", text)


def clean_question(question: str) -> str | None:
    question = normalize_text(question)
    question = re.sub(r"^(the\s+question\s+left\s+for\s+you\s+is\s+)", "", question, flags=re.IGNORECASE)
    question = re.sub(
        r"^(?:and\s+)?(?:the\s+)?(?:last\s+gu(?:e)?s[st]\s+)?(?:leaves?\s+)?(?:a\s+)?question\s+(?:for\s+you|for\s+the\s+next\s+guest|left\s+for\s+you)?\s*(?:is|was)?\s*",
        "",
        question,
        flags=re.IGNORECASE,
    )
    start_match = QUESTION_START_PATTERN.search(question)
    if start_match:
        question = question[start_match.start() :]
    question = re.sub(r'^[\'"“”]+|[\'"“”]+$', "", question)
    question = question.strip()
    if not question:
        return None
    if "?" in question:
        question = question[: question.find("?") + 1]
    if len(question) < 10:
        return None
    return question


def fallback_question(text: str) -> str | None:
    tail = text[-12000:]
    for pattern in FALLBACK_SPLIT_PATTERNS:
        match = pattern.search(tail)
        if match:
            tail = tail[: match.start()]
            break

    sentences = [normalize_text(sentence) for sentence in split_sentences(tail)]
    question_candidates = [sentence for sentence in sentences if sentence.endswith("?")]

    for candidate in reversed(question_candidates):
        lower = candidate.lower()
        if any(
            hint in lower
            for hint in (
                "what",
                "how",
                "why",
                "when",
                "where",
                "who",
                "which",
                "would",
                "could",
                "do you",
                "are you",
                "is there",
                "can you",
            )
        ):
            return clean_question(candidate)
    return None


def extract_question(transcript: str) -> tuple[str | None, str]:
    normalized = normalize_text(transcript)
    tail = normalized[-18000:]

    anchor_match = None
    for pattern in ANCHOR_PATTERNS:
        for match in pattern.finditer(tail):
            if anchor_match is None or match.start() > anchor_match.start():
                anchor_match = match

    if anchor_match:
        anchored_tail = tail[anchor_match.end() :]
        for sentence in split_sentences(anchored_tail[:900]):
            if "?" not in sentence:
                continue
            question = clean_question(sentence)
            if question:
                return question, "anchor"

    question = fallback_question(tail)
    if question:
        return question, "fallback-tail"

    return None, "unresolved"


def load_existing_questions() -> dict[str, dict[str, object]]:
    if not QUESTIONS_PATH.exists():
        return {}

    raw = json.loads(QUESTIONS_PATH.read_text())
    questions: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if isinstance(slug, str) and slug:
            questions[slug] = item
    return questions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-extract questions even when they already exist in questions.json or transcript front matter.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    existing_questions = load_existing_questions()
    updated = 0
    preserved = 0
    unresolved = 0

    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        episode = read_transcript_markdown(path)
        existing = existing_questions.get(slugify(episode.title))
        existing_question = existing.get("question") if isinstance(existing, dict) else None

        if not args.force_refresh and isinstance(existing_question, str) and existing_question.strip():
            episode.question = existing_question
            extraction_method = existing.get("question_extraction")
            if isinstance(extraction_method, str) and extraction_method:
                episode.extraction_method = extraction_method
            else:
                episode.extraction_method = "existing"
            write_transcript_markdown(episode)
            preserved += 1
            continue

        if not args.force_refresh and episode.question and episode.question.strip():
            preserved += 1
            continue

        question, method = extract_question(episode.transcript)
        episode.question = question
        episode.extraction_method = method
        write_transcript_markdown(episode)

        if question:
            updated += 1
        else:
            unresolved += 1

    print(
        f"Processed transcripts. Preserved: {preserved}. Extracted: {updated}. Unresolved: {unresolved}.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
