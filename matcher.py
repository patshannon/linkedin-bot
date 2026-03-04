"""
Job Matcher — Phase 1: Non-AI Keyword Weighting System

Reads scraped LinkedIn jobs from a CSV, scores each job against
a weighted keyword profile extracted from your resume, and outputs
the top matches to a new CSV file.

Usage:
    python matcher.py                       # auto-detects latest jobs_*.csv file
    python matcher.py --input jobs.csv      # use a specific file
    python matcher.py --top 20              # show top 20 matches (default: 25)
"""

import csv
import re
import glob
import os
import argparse
from datetime import datetime
from dataclasses import dataclass, field

# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION — Adjust these weights to tune your matching
# ──────────────────────────────────────────────────────────────────────

# Positive keywords: {keyword_or_phrase: weight}
# Higher weight = more important to you
POSITIVE_KEYWORDS: dict[str, int] = {
    # ── Core Stack (highest weight) ──
    "react": 10,
    "next.js": 10,
    "nextjs": 10,
    "typescript": 10,
    "node.js": 9,
    "nodejs": 9,
    "python": 9,

    # ── Frontend ──
    "javascript": 7,
    "tailwind": 6,
    "html": 4,
    "css": 4,
    "frontend": 6,
    "front-end": 6,
    "full-stack": 8,
    "full stack": 8,
    "fullstack": 8,

    # ── Backend & APIs ──
    "rest api": 6,
    "graphql": 7,
    "microservices": 7,
    "api": 4,

    # ── Databases & Caching ──
    "mongodb": 4,
    "postgresql": 3,
    "postgres": 3,
    "firestore": 7,
    "sql": 3,
    "caching": 4,

    # ── Cloud & DevOps ──
    "gcp": 7,
    "firebase": 6,
    "google cloud": 7,
    "cloudflare": 5,
    "cloudflare workers": 4,
    "cloud functions": 6,
    "docker": 4,
    "ci/cd": 5,
    "github actions": 5,

    # ── Testing ──
    "jest": 5,
    "playwright": 5,
    "testing": 3,
    "e2e testing": 6,
    "unit testing": 6,
    "integration testing": 6,

    # ── Auth ──
    "jwt": 4,
    "oauth": 4,
    "authentication": 3,
    "firebase auth": 7,
    "session management": 4,

    # ── Search & CMS ──
    "algolia": 6,
    "headless cms": 5,
    "cms": 3,
    "web components": 5,
    "sanity": 4,

    # ── Performance & Monitoring ──
    "core web vitals": 5,
    "lighthouse": 4,
    "monitoring": 3,
    "cloud logging": 4,

    # ── Design ──
    "figma": 4,

    # ── Soft / Role Signals ──
    "startup": 4,
    "mentorship": 3,
    "code review": 3,
    "system design": 5,
    "performance": 4,
    "seo": 4,
    "remote": 10,
    "senior": 8,
    "lead": 7,
    "tech lead": 8,

    # ── AI-Assisted Dev ──
    "claude": 3,
    "copilot": 3,
    "ai-assisted": 3,
}

# Negative keywords: {keyword_or_phrase: penalty}
# These SUBTRACT from the score (use positive numbers — they are subtracted)
NEGATIVE_KEYWORDS: dict[str, int] = {
    # ── Location Restrictions ──
    "on-site": 50,
    "onsite": 50,
    "hybrid": 50,
    "office": 15,

    # ── Clearance / Restrictions ──
    "security clearance": 50,
    "secret clearance": 50,
    "top secret": 50,
    "ts/sci": 50,
    "public trust": 30,
    "us citizen": 40,
    "u.s. citizen": 40,
    "united states citizen": 40,

    # ── Unrelated Stacks ──
    "c++": 10,
    "c#": 10,
    ".net": 10,
    "java ": 10,  # trailing space to avoid matching "javascript"
    "angular": 5,
    "vue": 10,
    "ruby on rails": 10,
    "ruby": 10,
    "php": 10,
    "scala": 10,
    "rust": 10,
    "swift": 10,
    "kotlin": 10,
    "objective-c": 10,
    "flutter": 10,
    "react native": 3,
    "kubernetes": 10,
    "golang": 10,

    # ── Seniority Mismatch ──
    "staff engineer": 30,
    "staff software": 30,
    "principal": 50,
    "junior": 10,
    "intern": 15,
    "internship": 15,
    "entry level": 8,
    "entry-level": 8,
    "new grad": 5,

    # ── Domain Mismatch (optional — remove if you're open to these) ──
    "embedded": 5,
    "firmware": 5,
    "fpga": 8,
    "verilog": 8,
}

# ──────────────────────────────────────────────────────────────────────
# SCORING ENGINE
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ScoredJob:
    job_title: str
    company_name: str
    job_link: str
    score: int
    matched_positive: list[str] = field(default_factory=list)
    matched_negative: list[str] = field(default_factory=list)


def normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for consistent matching."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text


def score_experience(text: str) -> tuple[int, str]:
    """
    Find year-of-experience requirements and score based on fit for a 5+ year candidate.
    Returns (score_delta, label) where label is empty string if no requirement found.
    """
    # Intentionally strict: only match explicit "N+ years" requirements.
    # Avoids edge cases like timeline phrases (e.g., "in 1 year").
    matches = re.findall(r'(\d+)\s*\+\s*years?\b', text)
    if not matches:
        return 0, ""

    years = [int(m) for m in matches]
    min_req = min(years)

    if min_req == 5:
        return +15, f"exp: {min_req}+ yrs (+15)"   # ideal
    elif min_req in (4, 6):
        return +10, f"exp: {min_req}+ yrs (+10)"   # close to ideal
    elif min_req in (3, 7):
        return +5, f"exp: {min_req}+ yrs (+5)"     # still viable
    elif min_req <= 2:
        return -30, f"exp: {min_req}+ yrs (-30)"   # too junior
    elif min_req <= 10:
        return -15, f"exp: {min_req}+ yrs (-15)"   # stretch
    else:
        return -25, f"exp: {min_req}+ yrs (-25)"   # unrealistic


def score_job(job_description: str, job_title: str) -> tuple[int, list[str], list[str]]:
    """
    Score a job based on keyword matches in the description AND title.
    Title matches get a 1.5x bonus since they signal core role focus.
    Returns (score, matched_positive_keywords, matched_negative_keywords).
    """
    desc = normalize_text(job_description)
    title = normalize_text(job_title)
    combined = f"{title} {desc}"

    score = 0
    matched_pos: list[str] = []
    matched_neg: list[str] = []

    remote_friendly_signals = [
        "remote-friendly",
        "remote friendly",
        "remote-first",
        "remote first",
        "fully remote",
        "remote within",
    ]
    has_remote_friendly_signal = any(signal in combined for signal in remote_friendly_signals)

    for keyword, weight in POSITIVE_KEYWORDS.items():
        kw = keyword.lower()
        # Count occurrences in description
        desc_count = len(re.findall(re.escape(kw), desc))
        # Check title (bonus)
        title_match = 1 if kw in title else 0

        if desc_count > 0 or title_match > 0:
            # First occurrence gets full weight, additional occurrences get diminishing returns
            keyword_score = weight + (min(desc_count - 1, 3) * (weight // 3)) + (title_match * (weight // 2))
            score += keyword_score
            matched_pos.append(f"{keyword} (+{keyword_score})")

    for keyword, penalty in NEGATIVE_KEYWORDS.items():
        kw = keyword.lower()
        if kw == "hybrid" and has_remote_friendly_signal:
            continue
        if kw in combined:
            score -= penalty
            matched_neg.append(f"{keyword} (-{penalty})")

    exp_delta, exp_label = score_experience(desc)
    if exp_label:
        score += exp_delta
        if exp_delta >= 0:
            matched_pos.append(exp_label)
        else:
            matched_neg.append(exp_label)

    return score, matched_pos, matched_neg


def load_jobs(file_path: str) -> list[dict[str, str]]:
    """Load jobs from a CSV file."""
    jobs: list[dict[str, str]] = []
    with open(file_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            jobs.append(row)
    return jobs


def strip_tracking_params(url: str) -> str:
    """Return just the URL path, dropping LinkedIn tracking query params."""
    return url.split("?")[0].rstrip("/")


def load_applied_links(path: str = "applications.csv") -> set[str]:
    """Load job links that have already been applied to, normalized to path-only."""
    if not os.path.exists(path):
        return set()
    with open(path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {
            strip_tracking_params(row.get("job_link", "").strip())
            for row in reader
            if row.get("job_link", "").strip()
        }


def match_jobs(jobs: list[dict[str, str]]) -> list[ScoredJob]:
    """Score, deduplicate, and rank all jobs."""
    scored: list[ScoredJob] = []
    seen_links: set[str] = set()
    applied_links = load_applied_links()
    skipped_applied = 0

    for job in jobs:
        # Skip already-applied jobs
        link = job.get("job_link", "").strip()
        if strip_tracking_params(link) in applied_links:
            skipped_applied += 1
            continue

        # Deduplicate by job link OR by title+company (LinkedIn posts same role with different IDs)
        title_company_key = (job.get("job_title", "").strip().lower(), job.get("company_name", "").strip().lower())
        if link in seen_links or title_company_key in seen_links:
            continue
        seen_links.add(link)
        seen_links.add(title_company_key)

        description = job.get("job_description", "")
        title = job.get("job_title", "")
        score, pos, neg = score_job(description, title)
        scored.append(
            ScoredJob(
                job_title=title.strip(),
                company_name=job.get("company_name", "").strip(),
                job_link=link,
                score=score,
                matched_positive=pos,
                matched_negative=neg,
            )
        )

    if skipped_applied > 0:
        print(f"Skipped {skipped_applied} already-applied job(s).")
    dupes_removed = len(jobs) - len(scored) - skipped_applied
    if dupes_removed > 0:
        print(f"Removed {dupes_removed} duplicate job(s).")

    scored.sort(key=lambda j: j.score, reverse=True)
    return scored


def export_results(scored_jobs: list[ScoredJob], output_path: str) -> None:
    """Export scored jobs to a CSV file."""
    fieldnames = ["rank", "score", "job_title", "company_name", "job_link", "matched_keywords", "penalties"]
    with open(output_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i, job in enumerate(scored_jobs, start=1):
            writer.writerow(
                {
                    "rank": i,
                    "score": job.score,
                    "job_title": job.job_title,
                    "company_name": job.company_name,
                    "job_link": job.job_link,
                    "matched_keywords": "; ".join(job.matched_positive),
                    "penalties": "; ".join(job.matched_negative),
                }
            )


def print_results(scored_jobs: list[ScoredJob], top_n: int) -> None:
    """Pretty-print the top N results to the terminal."""
    print(f"\n{'='*80}")
    print(f"  TOP {min(top_n, len(scored_jobs))} JOB MATCHES")
    print(f"{'='*80}\n")

    for i, job in enumerate(scored_jobs[:top_n], start=1):
        score_bar = "█" * min(job.score // 3, 40)  # visual score bar
        print(f"  #{i:>2}  Score: {job.score:>4}  {score_bar}")
        print(f"       {job.job_title}")
        print(f"       {job.company_name}")
        pos_keywords = [kw for kw in job.matched_positive if not kw.startswith("exp:")]
        neg_keywords = [kw for kw in job.matched_negative if not kw.startswith("exp:")]
        exp_label = next((kw for kw in job.matched_positive + job.matched_negative if kw.startswith("exp:")), None)
        if pos_keywords:
            print(f"       ✅ {', '.join(kw.split(' (')[0] for kw in pos_keywords[:8])}")
        if neg_keywords:
            print(f"       ❌ {', '.join(kw.split(' (')[0] for kw in neg_keywords)}")
        if exp_label:
            print(f"       🗓  {exp_label}")
        print(f"       🔗 {job.job_link[:80]}...")
        print()

    # Summary stats
    scores = [j.score for j in scored_jobs]
    print(f"{'─'*80}")
    print(f"  Total jobs analyzed: {len(scored_jobs)}")
    print(f"  Score range: {min(scores)} — {max(scores)}")
    print(f"  Average score: {sum(scores) / len(scores):.1f}")
    print(f"{'─'*80}\n")


# ──────────────────────────────────────────────────────────────────────
# FILE DISCOVERY
# ──────────────────────────────────────────────────────────────────────

def find_latest_jobs_csv() -> str | None:
    """
    Find the most recent jobs_*.csv file by filesystem modification time.
    The scraper outputs files like jobs_2026-03-04_12-09-00.csv.
    Falls back to jobs.csv if no timestamped files exist.
    """
    # Look for timestamped files first (jobs_YYYY-MM-DD_HH-MM-SS.csv)
    timestamped_files = glob.glob("jobs_*.csv")
    if timestamped_files:
        # Sort by modification time, newest first
        timestamped_files.sort(key=os.path.getmtime, reverse=True)
        return timestamped_files[0]

    # Fall back to plain jobs.csv
    if os.path.exists("jobs.csv"):
        return "jobs.csv"

    return None


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Score and rank LinkedIn jobs by keyword match.")
    parser.add_argument("--input", "-i", default=None, help="Path to input CSV file (default: auto-detect latest jobs_*.csv)")
    parser.add_argument("--output", "-o", default=None, help="Path to output CSV file (default: best_matches_<timestamp>.csv)")
    parser.add_argument("--top", "-t", type=int, default=25, help="Number of top matches to display (default: 25)")
    args = parser.parse_args()

    # Resolve input file
    if args.input:
        input_file = args.input
        if not os.path.exists(input_file):
            print(f"❌ File not found: {input_file}")
            return
    else:
        input_file = find_latest_jobs_csv()
        if not input_file:
            print("❌ No jobs CSV files found. Run the scraper first:")
            print("   python scraper.py")
            return
        print(f"📂 Auto-detected latest file: {input_file}")

    # Resolve output file
    output_file = args.output or f"best_matches_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"

    print(f"Loading jobs from {input_file}...")
    jobs = load_jobs(input_file)
    print(f"Loaded {len(jobs)} jobs. Scoring...")

    scored_jobs = match_jobs(jobs)

    print_results(scored_jobs, args.top)
    export_results(scored_jobs, output_file)
    print(f"Full ranked results exported to {output_file}")


if __name__ == "__main__":
    main()
