#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from extract_questions import extract_question, read_transcript_markdown, slugify


ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = ROOT / "transcripts"
QUESTIONS_PATH = ROOT / "questions.json"

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business": (
        "business",
        "company",
        "career",
        "money",
        "wealth",
        "sales",
        "startup",
        "founder",
        "millionaire",
        "success",
        "leader",
        "leadership",
        "work",
    ),
    "relationships": (
        "relationship",
        "dating",
        "marriage",
        "partner",
        "family",
        "friend",
        "people",
        "love",
        "respect",
        "children",
        "parent",
    ),
    "health": (
        "health",
        "sleep",
        "food",
        "brain",
        "stress",
        "body",
        "trauma",
        "longevity",
        "fitness",
        "gut",
        "fat",
        "hormone",
        "dementia",
    ),
    "beliefs": (
        "god",
        "faith",
        "belief",
        "religion",
        "spiritual",
        "christian",
        "atheist",
        "meaning",
        "purpose",
        "truth",
    ),
    "society": (
        "future",
        "world",
        "humanity",
        "society",
        "culture",
        "politics",
        "america",
        "country",
        "technology",
        "ai",
        "war",
        "civilization",
    ),
    "life": (
        "life",
        "live",
        "fear",
        "regret",
        "happy",
        "happiness",
        "learn",
        "mistake",
        "change",
        "best",
        "worst",
        "hear",
        "understand",
        "self",
    ),
}

SUSPICIOUS_PHRASES = (
    "who they're leaving it for",
    "question left for you",
    "last guest",
    "next guest",
    "closing tradition",
    "what is it",
    "who's it for",
    "whos it for",
    "do you keep up",
    "slash had the chance",
    "if you understand that process",
    "are you prepared for recognition",
    "the universe keeps putting in front of you",
)

STRONG_STARTS = (
    "what ",
    "how ",
    "why ",
    "when ",
    "where ",
    "who ",
    "which ",
    "if you ",
    "what's ",
    "do you ",
    "would you ",
    "could you ",
    "can you ",
    "are you ",
    "is there ",
    "should ",
)


def categorize_question(title: str, question: str) -> str:
    haystack = f"{title} {question}".lower()
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(keyword in haystack for keyword in keywords)
        if score:
            scores[category] = score
    if not scores:
        return "general"
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[0][0]


def normalize_question_text(question: str) -> str:
    question = question.strip()
    if not question:
        return question

    first = question[0]
    if first.isalpha():
        return first.upper() + question[1:]
    return question


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


def score_question_confidence(question: str, extraction_method: str) -> int:
    lower = question.lower().strip()
    score = 0.0

    if extraction_method == "anchor":
        score += 0.58
    elif extraction_method == "fallback-tail":
        score += 0.34
    else:
        score += 0.18

    word_count = len(question.replace("?", "").split())
    if 5 <= word_count <= 18:
        score += 0.18
    elif 3 <= word_count <= 24:
        score += 0.08
    else:
        score -= 0.1

    if question.endswith("?"):
        score += 0.08
    else:
        score -= 0.08

    if any(lower.startswith(prefix) for prefix in STRONG_STARTS):
        score += 0.12

    if ">>" in question or '"' in question:
        score -= 0.18

    if any(phrase in lower for phrase in SUSPICIOUS_PHRASES):
        score -= 0.42

    if len(lower) < 18:
        score -= 0.12

    if lower in {"what is it?", "who's it for?", "whos it for?", "do you keep up?"}:
        score -= 0.28

    if " and " in lower and word_count > 20:
        score -= 0.12

    score = max(0.0, min(0.99, score))
    return round(score * 100)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-extract questions even when an entry already exists in questions.json.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    questions = []
    unresolved = []
    existing_questions = load_existing_questions()

    for path in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        episode = read_transcript_markdown(path)
        slug = slugify(episode.title)
        existing = existing_questions.get(slug)

        existing_question = existing.get("question") if isinstance(existing, dict) else None
        if (
            not args.force_refresh
            and isinstance(existing_question, str)
            and existing_question.strip()
        ):
            questions.append(
                {
                    "slug": slug,
                    "title": episode.title,
                    "video_url": episode.url,
                    "question": existing_question,
                    "category": existing.get("category") or categorize_question(episode.title, existing_question),
                    "question_extraction": existing.get("question_extraction") or "existing",
                    "confidence": existing.get("confidence")
                    if isinstance(existing.get("confidence"), int)
                    else score_question_confidence(existing_question, "existing"),
                    "hidden": existing.get("hidden")
                    if isinstance(existing.get("hidden"), bool)
                    else (
                        score_question_confidence(existing_question, "existing") < 50
                    ),
                }
            )
            continue

        if episode.question and episode.question.strip() and not args.force_refresh:
            question = episode.question
            method = episode.extraction_method or "existing"
        else:
            question, method = extract_question(episode.transcript)

        if not question:
            unresolved.append(path.name)
            continue
        question = normalize_question_text(question)
        confidence = score_question_confidence(question, method)

        questions.append(
            {
                "slug": slug,
                "title": episode.title,
                "video_url": episode.url,
                "question": question,
                "category": categorize_question(episode.title, question),
                "question_extraction": method,
                "confidence": confidence,
                "hidden": confidence < 50,
            }
        )

    QUESTIONS_PATH.write_text(json.dumps(questions, indent=2) + "\n")

    print(f"Wrote {len(questions)} questions to {QUESTIONS_PATH.name}")
    if unresolved:
        print(f"Skipped {len(unresolved)} transcripts without a resolved question")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
