"""
Interview Prep Assistant — AI-powered Q&A using your job application context.

Loads the job description, tailored resume, and cover letter from an output folder
and starts a multi-turn interactive session to help you prepare for interviews.

Usage:
    python interview.py output_2024-01-01_12-00-00
    python interview.py output_2024-01-01_12-00-00 --config my_config.yaml
"""

import os
import glob
import argparse
import sys
import threading
import itertools
import time

import yaml
from anthropic import Anthropic


DEFAULT_CONFIG_PATH = "ai_config.yaml"


def spinning_cursor(stop_event: threading.Event) -> None:
    for frame in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        sys.stdout.write(f"\r{frame} Thinking...")
        sys.stdout.flush()
        time.sleep(0.1)
    sys.stdout.write("\r" + " " * 15 + "\r")
    sys.stdout.flush()

SYSTEM_PROMPT_TEMPLATE = """You are an expert interview coach helping a candidate prepare for a job interview.

You have full context about the job they applied for and their application materials. Use this context to give
specific, tailored answers — not generic advice. Reference actual details from the resume and job description.

When answering interview questions on behalf of the candidate:
- Write in first person as the candidate
- Be specific — reference real projects, metrics, and experience from the resume
- Be concise and natural — avoid corporate buzzwords and filler phrases
- Structure answers using the STAR method (Situation, Task, Action, Result) where appropriate, but don't label it explicitly
- Keep answers to 2-4 paragraphs unless asked for shorter/longer

When giving coaching advice:
- Be direct and practical
- Point out what to emphasize given this specific job's requirements

---

CANDIDATE: {name}
APPLYING FOR: {job_title} at {company_name}

---

JOB DESCRIPTION:
{job_description}

---

TAILORED RESUME:
{resume}

---

COVER LETTER:
{cover_letter}
"""


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def find_file(folder: str, pattern: str) -> str | None:
    matches = glob.glob(os.path.join(folder, pattern))
    return matches[0] if matches else None


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def load_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.strip().startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return None


def parse_job_info(jd_text: str) -> tuple[str, str]:
    """Extract job title and company name from the job_description.md header."""
    job_title = "Unknown Role"
    company_name = "Unknown Company"
    for line in jd_text.splitlines():
        line = line.strip()
        if line.startswith("# ") and " at " in line:
            parts = line[2:].split(" at ", 1)
            job_title = parts[0].strip()
            company_name = parts[1].strip()
            break
    return job_title, company_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Interview prep assistant using your job application context.")
    parser.add_argument("folder", help="Output folder from generator.py (e.g. output_2024-01-01_12-00-00)")
    parser.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH, help=f"Path to AI config YAML (default: {DEFAULT_CONFIG_PATH})")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"❌ Folder not found: {args.folder}")
        return

    config = load_config(args.config)
    personal = config.get("personal", {})
    name = personal.get("name", "the candidate")
    model = config.get("model", "claude-sonnet-4-6")

    # Load context files
    print(f"\n🔍 Loading context from {args.folder}/")

    jd_file = find_file(args.folder, "*_job_description.md")
    resume_file = find_file(args.folder, "*_resume.md")
    cl_file = find_file(args.folder, "*_cover_letter.md")

    if not jd_file:
        print("❌ No job_description.md found. Re-run generator.py to regenerate this output folder.")
        return

    jd_text = read_file(jd_file)
    job_title, company_name = parse_job_info(jd_text)
    print(f"   ✅ Job description: {job_title} at {company_name}")

    resume_text = ""
    if resume_file:
        resume_text = read_file(resume_file)
        print(f"   ✅ Tailored resume loaded")
    else:
        print(f"   ⚠️  No tailored resume found")

    cl_text = ""
    if cl_file:
        cl_text = read_file(cl_file)
        print(f"   ✅ Cover letter loaded")
    else:
        print(f"   ⚠️  No cover letter found")

    api_key = load_api_key()
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not found.")
        print("   Set it as an environment variable or add it to a .env file.")
        return

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        name=name,
        job_title=job_title,
        company_name=company_name,
        job_description=jd_text,
        resume=resume_text or "(not available)",
        cover_letter=cl_text or "(not available)",
    )

    client = Anthropic(api_key=api_key)
    conversation: list[dict] = []

    print(f"\n{'='*60}")
    print(f"  Interview Prep: {job_title} at {company_name}")
    print(f"  Model: {model}")
    print(f"  Type 'quit' or 'exit' to end the session")
    print(f"{'='*60}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSession ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit", "q"}:
            print("Session ended. Good luck!")
            break

        conversation.append({"role": "user", "content": user_input})

        try:
            stop_spinner = threading.Event()
            spinner = threading.Thread(target=spinning_cursor, args=(stop_spinner,), daemon=True)
            spinner.start()

            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=conversation,
            )

            stop_spinner.set()
            spinner.join()

            reply = response.content[0].text
            conversation.append({"role": "assistant", "content": reply})
            print(f"\nAssistant: {reply}\n")
        except Exception as e:
            print(f"❌ API error: {e}\n")
            # Remove the failed user message so conversation stays valid
            conversation.pop()


if __name__ == "__main__":
    main()
