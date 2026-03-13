#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from extract_questions import Episode, read_transcript_markdown, transcript_path_for_video_id, write_transcript_markdown


ROOT = Path(__file__).resolve().parent.parent
LINKS_PATH = ROOT / "links.json"
ENV_PATH = ROOT / ".env"
TRANSCRIPTS_DIR = ROOT / "transcripts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Refetch transcripts even when a local transcript markdown file already exists.",
    )
    return parser.parse_args()


def get_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.lstrip("/")
    return parse_qs(parsed.query).get("v", [""])[0]


def load_links() -> list[str]:
    raw_links = json.loads(LINKS_PATH.read_text())
    unique: list[str] = []
    seen: set[str] = set()
    for link in raw_links:
        video_id = get_video_id(link)
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        unique.append(f"https://www.youtube.com/watch?v={video_id}")
    return unique


def run_command(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(stderr or f"Command failed: {' '.join(args)}")
    return result.stdout.strip()


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def fetch_metadata(url: str) -> tuple[str, str | None]:
    raw = run_command(["yt-dlp", "--dump-single-json", "--skip-download", url])
    data = json.loads(raw)
    title = (data.get("title") or "").strip()
    description = data.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None
    if not title:
        raise RuntimeError(f"Missing title in metadata for {url}")
    return title, description


def build_transcript_api():
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api.proxies import WebshareProxyConfig

    load_env_file(ENV_PATH)
    username = os.environ.get("WEBSHARE_PROXY_USERNAME")
    password = os.environ.get("WEBSHARE_PROXY_PASSWORD")
    if not username or not password:
        raise RuntimeError("Missing WEBSHARE_PROXY_USERNAME or WEBSHARE_PROXY_PASSWORD in .env")

    proxy_config = WebshareProxyConfig(
        proxy_username=username,
        proxy_password=password,
    )
    return YouTubeTranscriptApi(proxy_config=proxy_config)


def fetch_transcript(api, video_id: str) -> str:
    fetched = api.fetch(video_id, languages=("en",))
    return " ".join(snippet.text.strip() for snippet in fetched if snippet.text.strip()).strip()


def existing_transcript_video_ids() -> set[str]:
    video_ids: set[str] = set()
    for path in TRANSCRIPTS_DIR.glob("*.md"):
        try:
            episode = read_transcript_markdown(path)
        except Exception:
            continue
        video_ids.add(episode.video_id)
    return video_ids


def main() -> int:
    args = parse_args()
    if not LINKS_PATH.exists():
        print(f"Missing {LINKS_PATH}", file=sys.stderr)
        return 1

    links = load_links()
    linked_video_ids = {get_video_id(url) for url in links}
    existing_before = existing_transcript_video_ids()
    matched_existing_before = len(linked_video_ids & existing_before)
    pending_before = len(linked_video_ids - existing_before)

    print(
        "Preflight: "
        f"{len(links)} linked videos, "
        f"{matched_existing_before} transcripts already present, "
        f"{pending_before} missing.",
        file=sys.stderr,
    )

    transcript_api = build_transcript_api()
    fetched_count = 0
    skipped_count = 0
    failed_count = 0

    for index, url in enumerate(links, start=1):
        video_id = get_video_id(url)
        print(f"Progress {index}/{len(links)}: {video_id}", file=sys.stderr)
        existing_path = transcript_path_for_video_id(video_id)
        if existing_path and not args.force_refresh:
            print(f"Skipping {video_id}; found existing transcript at {existing_path.name}", file=sys.stderr)
            skipped_count += 1
            continue

        existing_episode = read_transcript_markdown(existing_path) if existing_path and existing_path.exists() else None

        try:
            title, description = fetch_metadata(url)
            transcript = fetch_transcript(transcript_api, video_id)
        except Exception as exc:  # noqa: BLE001
            print(f"Failed for {video_id}: {exc}", file=sys.stderr)
            failed_count += 1
            continue

        episode = Episode(
            video_id=video_id,
            url=url,
            title=title,
            description=description,
            transcript=transcript,
            question=existing_episode.question if existing_episode else None,
            extraction_method=existing_episode.extraction_method if existing_episode else "unresolved",
        )
        write_transcript_markdown(episode)
        fetched_count += 1

    existing_after = existing_transcript_video_ids()
    matched_existing_after = len(linked_video_ids & existing_after)
    missing_after = len(linked_video_ids - existing_after)

    print(
        "Done: "
        f"{len(links)} linked videos, "
        f"{matched_existing_after} transcripts present locally, "
        f"{missing_after} still missing, "
        f"{fetched_count} fetched this run, "
        f"{skipped_count} skipped existing, "
        f"{failed_count} failed.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
