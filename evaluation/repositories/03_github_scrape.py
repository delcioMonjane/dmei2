"""
03_github_scrape.py  (v3 - working)
=====================================
Two-phase approach:
  Phase A) Use the REPOSITORY search API (supports date filters) to find
           repos created after --since that contain Dockerfiles.
  Phase B) For each repo, fetch the Dockerfile directly via the Contents API.

This avoids the code search API's lack of date filtering support entirely.

Rate limits:
  - Repository search : 30 req/min (authenticated)
  - Contents API      : 5000 req/hour (authenticated) — effectively unlimited

Usage:
    export GITHUB_TOKEN=ghp_yourtoken
    python 03_github_scrape.py \
        --output ../corpus/github_raw
        --count  5000 \
        --since  2022-03-20
"""

import argparse
import hashlib
import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── SSL context (fixes macOS certificate issues) ──────────────────────────────

SSL_CTX = ssl.create_default_context()
try:
    import certifi
    SSL_CTX = ssl.create_default_context(cafile=certifi.where())
    log.debug("Using certifi CA bundle")
except ImportError:
    pass

# ── GitHub API ────────────────────────────────────────────────────────────────

REPO_SEARCH_URL = "https://api.github.com/search/repositories"
CONTENTS_URL    = "https://api.github.com/repos/{repo}/contents/{path}"
RAW_URL         = "https://raw.githubusercontent.com/{repo}/{branch}/{path}"


def gh_get(url: str, token: str, params: dict | None = None) -> dict | None:
    if params:
        qs  = urllib.parse.urlencode(params)
        url = f"{url}?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Authorization",        f"Bearer {token}")
    req.add_header("Accept",               "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent",           "dockerfile-flakiness-research/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 403 or e.code == 429:
            reset = e.headers.get("X-RateLimit-Reset", "")
            wait  = 65
            if reset:
                wait = max(int(reset) - int(time.time()) + 5, 65)
            log.warning(f"Rate limited ({e.code}). Sleeping {wait}s.")
            time.sleep(wait)
            return None
        if e.code == 404:
            return None
        log.warning(f"HTTP {e.code} for {url[:80]}: {body[:100]}")
        return None
    except Exception as e:
        log.warning(f"Request error: {e}")
        return None


def fetch_raw(repo: str, branch: str, path: str, token: str) -> str | None:
    url = RAW_URL.format(repo=repo, branch=branch, path=path)
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("User-Agent",    "dockerfile-flakiness-research/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def looks_like_dockerfile(text: str) -> bool:
    for line in text.strip().splitlines()[:15]:
        if re.match(r"^\s*FROM\s+", line, re.IGNORECASE):
            return True
    return False


def sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def safe_filename(repo: str, path: str, h: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", f"{repo}__{path}")[:80]
    return f"{slug}__{h}.dockerfile"


# ── Dockerfile discovery in a repo ───────────────────────────────────────────

DOCKERFILE_NAMES = ["Dockerfile", "dockerfile"]

def find_dockerfiles_in_repo(repo: str, branch: str, token: str) -> list[str]:
    """
    Return paths of Dockerfiles found in the repo root and common subdirs.
    Checks root first, then one level of subdirectories via the tree API.
    """
    paths = []

    # Check root directly
    for name in DOCKERFILE_NAMES:
        data = gh_get(CONTENTS_URL.format(repo=repo, path=name), token)
        if data and isinstance(data, dict) and data.get("type") == "file":
            paths.append(name)

    if paths:
        return paths  # found at root, don't dig deeper to save API calls

    # Check one level of subdirectories via tree API (single call)
    tree_url = f"https://api.github.com/repos/{repo}/git/trees/{branch}"
    tree_data = gh_get(tree_url, token)
    if not tree_data:
        return paths

    for item in tree_data.get("tree", []):
        if item.get("type") == "blob":
            item_path = item.get("path", "")
            if item_path in DOCKERFILE_NAMES or item_path.endswith("/Dockerfile"):
                paths.append(item_path)

    return paths[:5]  # cap at 5 per repo to avoid overrepresentation


# ── Repository search queries ─────────────────────────────────────────────────

# These target repos with Dockerfiles across different ecosystems.
# Repository search DOES support created: date filter.
REPO_QUERIES = [
    "docker language:Python",
    "docker language:JavaScript",
    "docker language:Go",
    "docker language:Java",
    "docker language:Ruby",
    "docker language:Rust",
    "docker language:PHP",
    "docker language:TypeScript",
    "docker language:Shell",
    "docker language:C#",
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape Dockerfiles from GitHub (v3)")
    parser.add_argument("--output", default="./corpus/github_raw")
    parser.add_argument("--count",  type=int, default=3000, help="Target Dockerfile count")
    parser.add_argument("--since",  default="2022-03-20",   help="Repo created after (YYYY-MM-DD)")
    parser.add_argument("--token",  default="")
    parser.add_argument("--delay",  type=float, default=2.5, help="Sleep between repo search calls")
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token:
        log.error("No GitHub token. Set GITHUB_TOKEN env var or pass --token.")
        raise SystemExit(1)

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_hashes: set[str]  = set()
    seen_repos:  set[str]  = set()
    metadata:    list[dict] = []
    total = 0

    for query in REPO_QUERIES:
        if total >= args.count:
            break

        full_query = f"{query} created:>{args.since}"
        log.info(f"Repo query: {full_query}")

        # Repo search: up to 10 pages × 100 results = 1000 repos per query
        for page in range(1, 11):
            if total >= args.count:
                break

            time.sleep(args.delay)

            data = gh_get(REPO_SEARCH_URL, token, params={
                "q":        full_query,
                "sort":     "updated",
                "order":    "desc",
                "per_page": 100,
                "page":     page,
            })

            if data is None:
                log.warning("  No data returned, moving to next query")
                break

            repos = data.get("items", [])
            total_count = data.get("total_count", "?")
            log.info(f"  page {page}: {total_count} total repos, got {len(repos)} this page")

            if not repos:
                break

            for repo_obj in repos:
                if total >= args.count:
                    break

                repo_name  = repo_obj.get("full_name", "")
                branch     = repo_obj.get("default_branch", "main")
                created_at = repo_obj.get("created_at", "")

                if not repo_name or repo_name in seen_repos:
                    continue
                seen_repos.add(repo_name)

                # Find Dockerfiles in this repo
                time.sleep(0.5)
                paths = find_dockerfiles_in_repo(repo_name, branch, token)

                for path in paths:
                    if total >= args.count:
                        break

                    time.sleep(0.3)
                    content = fetch_raw(repo_name, branch, path, token)

                    if not content or not looks_like_dockerfile(content):
                        continue

                    h = sha256_short(content)
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)

                    fname = safe_filename(repo_name, path, h)
                    (output_dir / fname).write_text(content, encoding="utf-8", errors="replace")

                    metadata.append({
                        "filename":      fname,
                        "source":        "github_scrape",
                        "repo":          repo_name,
                        "original_path": path,
                        "branch":        branch,
                        "created_at":    created_at,
                        "html_url":      f"https://github.com/{repo_name}/blob/{branch}/{path}",
                        "content_hash":  h,
                        "size_bytes":    len(content.encode()),
                        "line_count":    len(content.splitlines()),
                    })
                    total += 1

                    if total % 100 == 0:
                        log.info(f"  scraped {total:,} Dockerfiles so far…")

        log.info(f"After query: {total:,} total Dockerfiles")

    # Write metadata
    meta_path = output_dir.parent / "github_metadata.jsonl"
    with open(meta_path, "w", encoding="utf-8") as fh:
        for record in metadata:
            fh.write(json.dumps(record) + "\n")

    log.info("=" * 60)
    log.info(f"Scraped {total:,} Dockerfiles from {len(seen_repos):,} repos")
    log.info(f"Metadata → {meta_path}")
    log.info(f"Files    → {output_dir}")
    log.info("Next: run 02_filter_corpus.py --dockerfiles ../corpus/github_raw ...")


if __name__ == "__main__":
    main()
