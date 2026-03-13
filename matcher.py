"""
Job Matcher — AI-Powered Matching with Claude Haiku

Reads scraped LinkedIn jobs from a CSV, sends them in batches to Claude Haiku
along with your resume, and gets AI-powered relevance scores and rankings.

Usage:
    python matcher.py                       # auto-detects latest jobs_*.csv file
    python matcher.py --input jobs.csv      # use a specific file
    python matcher.py --top 20              # show top 20 matches (default: 25)
    python matcher.py --resume my_resume.md # use a different resume
"""

import csv
import json
import re
import glob
import os
import argparse
from datetime import datetime
from dataclasses import dataclass

from anthropic import Anthropic

# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────

MODEL = "claude-sonnet-4-6"
BATCH_SIZE = 50
RESUME_PATH = "base_resume.md"


# ──────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ScoredJob:
    job_title: str
    company_name: str
    job_link: str
    score: int
    pros: str = ""
    cons: str = ""


# ──────────────────────────────────────────────────────────────────────
# API KEY
# ──────────────────────────────────────────────────────────────────────


def get_api_key() -> str | None:
    """Load ANTHROPIC_API_KEY from environment or .env file."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ──────────────────────────────────────────────────────────────────────
# RESUME & AI SCORING
# ──────────────────────────────────────────────────────────────────────


def load_resume(path: str = RESUME_PATH) -> str:
    """Load the base resume markdown."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def score_batch(
    client: Anthropic,
    jobs_batch: list[dict[str, str]],
    resume: str,
    batch_num: int,
    total_batches: int,
) -> list[dict]:
    """Send a batch of jobs to Claude Haiku for scoring."""
    jobs_text = ""
    for i, job in enumerate(jobs_batch):
        jobs_text += f"\n---JOB {i}---\n"
        jobs_text += f"Title: {job.get('job_title', '').strip()}\n"
        jobs_text += f"Company: {job.get('company_name', '').strip()}\n"
        jobs_text += f"Description: {job.get('job_description', '').strip()}\n"

    prompt = f"""You are a job matching assistant. Score each job for how well it matches this candidate's resume.

<resume>
{resume}
</resume>

IMPORTANT CONTEXT about the candidate:
- Located in Nova Scotia, Canada. MUST be remote-friendly to NS.
- Jobs requiring on-site, hybrid, security clearance, or US citizenship are POOR fits (score low).
- Canadian remote jobs that list specific provinces but exclude Nova Scotia are POOR fits.
- Has 5+ years of experience. Junior/intern roles are poor fits. Staff/principal/10+ year roles are stretches.
- Core stack: React, Next.js, TypeScript, Node.js, Python, GCP/Firebase.
- Strong preference for full-stack or frontend-heavy roles at senior/lead level.

Score each job 0-100:
- 90-100: Exceptional match (core stack, right seniority, remote, interesting domain)
- 70-89: Strong match (most requirements align)
- 50-69: Decent match (some overlap, some gaps)
- 30-49: Weak match (significant mismatches in stack, seniority, or location)
- 0-29: Poor match (wrong stack, wrong level, location/clearance issues)

For each job, list:
- "pros": reasons this job is a GOOD fit for THIS SPECIFIC candidate (matching skills, relevant experience, compatible location, etc.)
- "cons": reasons this job is a POOR fit for THIS SPECIFIC candidate (skills they lack, stack mismatch, location issues, etc.)

A technology the candidate does NOT have experience with is ALWAYS a con, never a pro — even if the job offers it.

Return ONLY a JSON array, no other text. Each element must have these exact keys:
[
  {{"job_index": 0, "score": 85, "pros": "react, next.js, remote, 5+ years", "cons": "requires AWS experience"}},
  ...
]

<jobs>
{jobs_text}
</jobs>"""

    print(f"  Scoring batch {batch_num}/{total_batches} ({len(jobs_batch)} jobs)...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Strip markdown code fences if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    # Extract JSON array from response
    json_match = re.search(r'\[.*\]', text, re.DOTALL)
    if not json_match:
        print(f"  ⚠️  Batch {batch_num}: Could not parse AI response, skipping.")
        print(f"      Response preview: {text[:300]}")
        return []

    try:
        results = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Batch {batch_num}: Invalid JSON in AI response, skipping.")
        print(f"      Error: {e}")
        return []

    # Report token usage and cost
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000
    print(f"  ✓ Batch {batch_num} done — {input_tokens:,} in / {output_tokens:,} out (${cost:.4f})")

    return results


# ──────────────────────────────────────────────────────────────────────
# CSV & DEDUP HELPERS
# ──────────────────────────────────────────────────────────────────────


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


def deduplicate_jobs(jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove already-applied and duplicate jobs."""
    unique: list[dict[str, str]] = []
    seen_links: set[str] = set()
    seen_title_company: set[tuple[str, str]] = set()
    applied_links = load_applied_links()
    skipped_applied = 0

    for job in jobs:
        link = job.get("job_link", "").strip()
        if strip_tracking_params(link) in applied_links:
            skipped_applied += 1
            continue

        title_company_key = (
            job.get("job_title", "").strip().lower(),
            job.get("company_name", "").strip().lower(),
        )
        clean_link = strip_tracking_params(link)
        if clean_link in seen_links or title_company_key in seen_title_company:
            continue
        seen_links.add(clean_link)
        seen_title_company.add(title_company_key)
        unique.append(job)

    if skipped_applied > 0:
        print(f"Skipped {skipped_applied} already-applied job(s).")
    dupes_removed = len(jobs) - len(unique) - skipped_applied
    if dupes_removed > 0:
        print(f"Removed {dupes_removed} duplicate job(s).")

    return unique


# ──────────────────────────────────────────────────────────────────────
# MAIN MATCHING PIPELINE
# ──────────────────────────────────────────────────────────────────────


def match_jobs(jobs: list[dict[str, str]], resume: str, client: Anthropic) -> list[ScoredJob]:
    """Send jobs to Claude Haiku in batches and collect scores."""
    scored: list[ScoredJob] = []

    batches = [jobs[i:i + BATCH_SIZE] for i in range(0, len(jobs), BATCH_SIZE)]
    total_batches = len(batches)
    total_cost = 0.0

    print(f"\n🤖 Scoring {len(jobs)} jobs in {total_batches} batch(es) using {MODEL}...\n")

    for batch_num, batch in enumerate(batches, start=1):
        results = score_batch(client, batch, resume, batch_num, total_batches)

        for result in results:
            idx = result.get("job_index", -1)
            if 0 <= idx < len(batch):
                job = batch[idx]
                scored.append(
                    ScoredJob(
                        job_title=job.get("job_title", "").strip(),
                        company_name=job.get("company_name", "").strip(),
                        job_link=job.get("job_link", "").strip(),
                        score=result.get("score", 0),
                        pros=result.get("pros", ""),
                        cons=result.get("cons", ""),
                    )
                )

    scored.sort(key=lambda j: j.score, reverse=True)
    return scored


# ──────────────────────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────────────────────


def export_results(scored_jobs: list[ScoredJob], output_path: str) -> None:
    """Export scored jobs to a CSV file."""
    fieldnames = ["rank", "score", "job_title", "company_name", "job_link", "pros", "cons"]
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
                    "pros": job.pros,
                    "cons": job.cons,
                }
            )


def print_results(scored_jobs: list[ScoredJob], top_n: int) -> None:
    """Pretty-print the top N results to the terminal."""
    print(f"\n{'='*80}")
    print(f"  TOP {min(top_n, len(scored_jobs))} JOB MATCHES (AI-scored)")
    print(f"{'='*80}\n")

    for i, job in enumerate(scored_jobs[:top_n], start=1):
        score_bar = "█" * (job.score // 2)
        print(f"  #{i:>2}  Score: {job.score:>3}/100  {score_bar}")
        print(f"       {job.job_title}")
        print(f"       {job.company_name}")
        if job.pros:
            print(f"       ✅ {job.pros}")
        if job.cons:
            print(f"       ❌ {job.cons}")
        print(f"       🔗 {job.job_link[:80]}...")
        print()

    scores = [j.score for j in scored_jobs]
    print(f"{'─'*80}")
    print(f"  Total jobs scored: {len(scored_jobs)}")
    print(f"  Score range: {min(scores)} — {max(scores)}")
    print(f"  Average score: {sum(scores) / len(scores):.1f}")
    print(f"{'─'*80}\n")


# ──────────────────────────────────────────────────────────────────────
# FILE DISCOVERY
# ──────────────────────────────────────────────────────────────────────


def find_latest_jobs_csv() -> str | None:
    """Find the most recent jobs_*.csv file by filesystem modification time."""
    timestamped_files = glob.glob("jobs_*.csv")
    if timestamped_files:
        timestamped_files.sort(key=os.path.getmtime, reverse=True)
        return timestamped_files[0]

    if os.path.exists("jobs.csv"):
        return "jobs.csv"

    return None


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-powered job matching with Claude Haiku.")
    parser.add_argument("--input", "-i", default=None, help="Path to input CSV (default: auto-detect latest jobs_*.csv)")
    parser.add_argument("--output", "-o", default=None, help="Path to output CSV (default: best_matches_<timestamp>.csv)")
    parser.add_argument("--top", "-t", type=int, default=25, help="Number of top matches to display (default: 25)")
    parser.add_argument("--resume", "-r", default=RESUME_PATH, help=f"Path to resume markdown (default: {RESUME_PATH})")
    args = parser.parse_args()

    # Check API key
    api_key = get_api_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not found.")
        print("   Set it as an environment variable:")
        print("     export ANTHROPIC_API_KEY=sk-ant-...")
        print("   Or create a .env file with:")
        print("     ANTHROPIC_API_KEY=sk-ant-...")
        return

    client = Anthropic(api_key=api_key)

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

    # Load resume
    if not os.path.exists(args.resume):
        print(f"❌ Resume not found: {args.resume}")
        return
    resume = load_resume(args.resume)
    print(f"📄 Loaded resume from {args.resume}")

    output_file = args.output or f"best_matches_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"

    print(f"Loading jobs from {input_file}...")
    jobs = load_jobs(input_file)
    print(f"Loaded {len(jobs)} jobs.")

    jobs = deduplicate_jobs(jobs)
    print(f"{len(jobs)} unique jobs to score.")

    scored_jobs = match_jobs(jobs, resume, client)

    if scored_jobs:
        print_results(scored_jobs, args.top)
        export_results(scored_jobs, output_file)
        print(f"Full ranked results exported to {output_file}")
    else:
        print("❌ No jobs were scored. Check API key and try again.")


if __name__ == "__main__":
    main()
