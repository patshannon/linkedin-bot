"""
LinkedIn Job Scraper — Scrapes public LinkedIn job listings using Playwright.

Features:
  - Multiple search queries (configurable)
  - Infinite scroll handling (scrolls until "You've viewed all jobs" appears)
  - Deduplication by job link
  - Error handling with retries
  - Rate limiting to avoid detection

Usage:
    python scraper.py                       # uses default config
    python scraper.py --max-jobs 100        # cap at 100 jobs per query
    python scraper.py --output my_jobs.csv  # custom output file
"""

import time
import csv
import random
import argparse
from datetime import datetime
from urllib.parse import quote_plus

from playwright.sync_api import sync_playwright, Page, Browser, TimeoutError as PlaywrightTimeout


# ──────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────────────

# Each query is a dict with search parameters.
# LinkedIn public search URL params:
#   f_JT=F        → Full-time
#   f_TPR=r86400  → Last 24 hours
#   f_WT=2        → Remote
#   geoId=101174742 → Canada
#   sortBy=R      → Most relevant
SEARCH_QUERIES: list[dict[str, str]] = [
    {
        "keywords": "software engineer",
        "geo_id": "101174742",  # Canada
        "job_type": "F",        # Full-time
        "time_range": "r86400", # Last 24 hours
        "remote": "2",          # Remote
    },
    {
        "keywords": "full stack developer",
        "geo_id": "101174742",
        "job_type": "F",
        "time_range": "r86400",
        "remote": "2",
    },
    {
        "keywords": "frontend developer",
        "geo_id": "101174742",
        "job_type": "F",
        "time_range": "r86400",
        "remote": "2",
    },
]

# Delay range (seconds) between requests to avoid rate limiting
MIN_DELAY = 1.0
MAX_DELAY = 3.0

# Default max jobs to scrape per query (0 = no limit, scrape all)
DEFAULT_MAX_JOBS = 0

# Maximum retries for a failed job detail page
MAX_RETRIES = 2


# ──────────────────────────────────────────────────────────────────────
# URL BUILDER
# ──────────────────────────────────────────────────────────────────────

def build_search_url(query: dict[str, str]) -> str:
    """Build a LinkedIn public job search URL."""
    keywords = quote_plus(query["keywords"])
    params = [
        f"keywords={keywords}",
        f"geoId={query.get('geo_id', '101174742')}",
        f"f_JT={query.get('job_type', 'F')}",
        f"f_TPR={query.get('time_range', 'r86400')}",
        f"f_WT={query.get('remote', '2')}",
        "sortBy=R",
        "origin=JOB_SEARCH_PAGE_JOB_FILTER",
        "spellCorrectionEnabled=true",
    ]
    return f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"


# ──────────────────────────────────────────────────────────────────────
# SCRAPING HELPERS
# ──────────────────────────────────────────────────────────────────────

def random_delay() -> None:
    """Sleep for a random duration to mimic human behavior."""
    time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))


def has_viewed_all_jobs(page: Page) -> bool:
    """Check if the 'You've viewed all jobs for this search' message is visible."""
    end_marker = page.locator(".inline-notification__text")
    if end_marker.count() > 0:
        try:
            text = end_marker.first.inner_text(timeout=1000)
            if "viewed all jobs" in text.lower():
                return True
        except Exception:
            pass
    return False


def scroll_and_load_all_jobs(page: Page, max_jobs: int = 0) -> int:
    """
    Scroll the infinite-scroll job list until either:
      1. The "You've viewed all jobs for this search" message appears
      2. We hit the max_jobs cap (if set)
      3. No new jobs load after multiple scroll attempts (safety)

    Returns the total number of job cards loaded.
    """
    previous_count = 0
    stale_rounds = 0
    max_stale = 5  # give up after 5 rounds with no new jobs

    while True:
        current_count = page.locator("ul.jobs-search__results-list li").count()

        # Check if we've hit the job cap
        if max_jobs > 0 and current_count >= max_jobs:
            print(f"    ⏹️  Reached job cap ({max_jobs}), stopping scroll")
            break

        # Check for end-of-results message
        if has_viewed_all_jobs(page):
            print(f"    ✅ Reached end of results ({current_count} jobs loaded)")
            break

        # Try clicking "See more jobs" button if it exists
        see_more = page.locator("button.infinite-scroller__show-more-button")
        if see_more.count() > 0:
            try:
                if see_more.is_visible():
                    see_more.click()
                    time.sleep(2.0)
            except Exception:
                pass

        # Scroll to bottom to trigger lazy loading
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1.5)

        # Check if new jobs loaded
        new_count = page.locator("ul.jobs-search__results-list li").count()
        if new_count == previous_count:
            stale_rounds += 1
            if stale_rounds >= max_stale:
                print(f"    ⚠️  No new jobs after {max_stale} scroll attempts ({new_count} total), stopping")
                break
        else:
            stale_rounds = 0
            if new_count % 25 == 0 or new_count - previous_count >= 10:
                print(f"    📜 Loaded {new_count} jobs so far...")

        previous_count = new_count

    return page.locator("ul.jobs-search__results-list li").count()


def extract_job_links(page: Page) -> list[str]:
    """Extract all job detail links from the loaded search results."""
    links: list[str] = []
    job_items = page.locator("ul.jobs-search__results-list li")
    count = job_items.count()

    for i in range(count):
        try:
            link_el = job_items.nth(i).locator("a.base-card__full-link")
            if link_el.count() > 0:
                href = link_el.get_attribute("href")
                if href:
                    links.append(href.strip())
        except Exception:
            continue

    return links


def scrape_job_detail(browser: Browser, job_link: str) -> dict[str, str] | None:
    """
    Open a job detail page and extract title, company, and description.
    Returns None if the page fails to load after retries.
    """
    for attempt in range(MAX_RETRIES + 1):
        detail_page = None
        try:
            detail_page = browser.new_page()
            detail_page.goto(job_link, wait_until="domcontentloaded", timeout=15000)
            detail_page.wait_for_selector("h1.top-card-layout__title", timeout=8000)

            job_title = detail_page.query_selector("h1.top-card-layout__title")
            company_el = detail_page.query_selector("a.topcard__org-name-link")
            description_el = detail_page.query_selector("div.show-more-less-html__markup")

            if not job_title:
                raise ValueError("Missing job title element")

            return {
                "job_title": job_title.inner_text().strip(),
                "company_name": company_el.inner_text().strip() if company_el else "Unknown",
                "job_link": job_link,
                "job_description": description_el.inner_text().strip() if description_el else "",
            }
        except (PlaywrightTimeout, ValueError, Exception) as e:
            if attempt < MAX_RETRIES:
                print(f"    ⚠️  Retry {attempt + 1}/{MAX_RETRIES} for {job_link[:60]}... ({e})")
                random_delay()
            else:
                print(f"    ❌ Failed after {MAX_RETRIES + 1} attempts: {job_link[:60]}...")
                return None
        finally:
            if detail_page:
                detail_page.close()

    return None


# ──────────────────────────────────────────────────────────────────────
# CSV EXPORT
# ──────────────────────────────────────────────────────────────────────

def export_jobs_to_csv(jobs: list[dict[str, str]], file_name: str) -> None:
    """Write jobs to a CSV file."""
    if not jobs:
        print("No jobs to export.")
        return

    field_names = ["job_title", "company_name", "job_link", "job_description"]
    with open(file_name, mode="w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=field_names)
        writer.writeheader()
        writer.writerows(jobs)


# ──────────────────────────────────────────────────────────────────────
# MAIN SCRAPER
# ──────────────────────────────────────────────────────────────────────

def scrape_query(browser: Browser, search_page: Page, query: dict[str, str], max_jobs: int, seen_links: set[str]) -> list[dict[str, str]]:
    """Scrape all jobs for a single search query using infinite scroll."""
    keyword_label = query["keywords"]
    jobs: list[dict[str, str]] = []
    url = build_search_url(query)

    print(f"\n  🌐 Loading search results for \"{keyword_label}\"...")
    try:
        search_page.goto(url, wait_until="domcontentloaded", timeout=15000)
        search_page.wait_for_selector("ul.jobs-search__results-list li", timeout=8000)
    except PlaywrightTimeout:
        print(f"  ⚠️  No results found for \"{keyword_label}\"")
        return jobs

    # Scroll to load all jobs via infinite scroll
    print(f"  📜 Scrolling to load all jobs...")
    total_loaded = scroll_and_load_all_jobs(search_page, max_jobs)
    print(f"  📋 Total job cards loaded: {total_loaded}")

    # Extract all links
    links = extract_job_links(search_page)

    # Filter out already-seen links (from previous queries)
    new_links = [link for link in links if link not in seen_links]
    print(f"  🔗 Found {len(links)} links ({len(new_links)} new, {len(links) - len(new_links)} already seen)")

    if not new_links:
        print(f"  ⚠️  All jobs already scraped from previous queries")
        return jobs

    # Apply max_jobs cap to the links we'll actually scrape
    if max_jobs > 0:
        new_links = new_links[:max_jobs]

    # Scrape each job detail page
    for i, link in enumerate(new_links):
        seen_links.add(link)
        print(f"    [{i + 1}/{len(new_links)}] Scraping: {link[:70]}...")
        job = scrape_job_detail(browser, link)
        if job:
            jobs.append(job)
        random_delay()

    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape LinkedIn job listings.")
    parser.add_argument("--output", "-o", default=None, help="Output CSV file name (default: jobs_<timestamp>.csv)")
    parser.add_argument("--max-jobs", "-m", type=int, default=DEFAULT_MAX_JOBS, help="Max jobs to scrape per query (default: 0 = no limit)")
    args = parser.parse_args()

    output_file = args.output or f"jobs_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.csv"

    print(f"🚀 LinkedIn Job Scraper")
    print(f"   Queries: {len(SEARCH_QUERIES)}")
    print(f"   Max jobs per query: {'unlimited' if args.max_jobs == 0 else args.max_jobs}")
    print(f"   Output: {output_file}")

    all_jobs: list[dict[str, str]] = []
    seen_links: set[str] = set()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        search_page = browser.new_page()

        for idx, query in enumerate(SEARCH_QUERIES, start=1):
            print(f"\n{'='*60}")
            print(f"  🔍 Query {idx}/{len(SEARCH_QUERIES)}: \"{query['keywords']}\"")
            print(f"{'='*60}")

            query_jobs = scrape_query(browser, search_page, query, args.max_jobs, seen_links)
            all_jobs.extend(query_jobs)
            print(f"\n  ✅ Got {len(query_jobs)} jobs for \"{query['keywords']}\"")

        search_page.close()
        browser.close()

    export_jobs_to_csv(all_jobs, output_file)

    print(f"\n{'='*60}")
    print(f"  🎉 Done! Scraped {len(all_jobs)} unique jobs across {len(SEARCH_QUERIES)} queries")
    print(f"  📁 Saved to {output_file}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
