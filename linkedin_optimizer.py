"""
LinkedIn Profile Optimizer — AI-powered LinkedIn profile improvement.

Uses your base resume and an AI "LinkedIn marketing expert" to generate
optimized versions of your LinkedIn profile sections: headline, about/bio,
experience descriptions, and skills.

Usage:
    python linkedin_optimizer.py                    # interactive menu
    python linkedin_optimizer.py --section headline # specific section
    python linkedin_optimizer.py --section about
    python linkedin_optimizer.py --section experience
    python linkedin_optimizer.py --section skills
    python linkedin_optimizer.py --section all      # optimize everything
    python linkedin_optimizer.py --config my_config.yaml

Requires:
    ANTHROPIC_API_KEY environment variable (or .env file)
"""

import argparse
import os
from datetime import datetime

import yaml
from anthropic import Anthropic

from generator import load_base_resume


DEFAULT_CONFIG_PATH = "ai_config.yaml"

SECTIONS = ["headline", "about", "experience", "skills"]

SYSTEM_PROMPT = """\
You are a LinkedIn marketing expert and personal branding strategist. \
You specialize in optimizing LinkedIn profiles to maximize visibility, \
engagement, and recruiter interest — particularly for senior developers \
and technical consultants in the software industry.

You understand LinkedIn's algorithm, how recruiters search, and what makes \
a profile stand out. You write in a confident, authentic voice — never \
generic or corporate-sounding. You avoid buzzwords like "synergy", \
"leverage", and "passionate" unless they genuinely add value.

Always use "Developer" instead of "Engineer" — this is intentional for \
the Canadian job market."""

HEADLINE_PROMPT = """\
Generate 5 optimized LinkedIn headline options based on this resume.

RESUME:
{resume}

RULES:
- Max 220 characters each (LinkedIn's limit)
- Front-load with the most searchable job title
- Include 2-3 relevant keywords recruiters search for
- Add a value proposition or differentiator where possible
- Mix styles: some title-focused, some value-focused, some hybrid
- Use pipes (|) or bullet points to separate elements — not em dashes
- Do NOT use emojis
- Do NOT start with "Helping..." or "Passionate about..."

Return each option on its own line, numbered 1-5. No extra commentary."""

ABOUT_PROMPT = """\
Write an optimized LinkedIn About/Bio section based on this resume.

RESUME:
{resume}

RULES:
- 1500-2000 characters (LinkedIn's sweet spot for the About section)
- Open with a strong hook in the first 2 lines (this is what shows before "see more")
- Write in first person
- Highlight key achievements with specific metrics
- Include relevant keywords naturally for LinkedIn search
- End with a soft call to action (open to opportunities, happy to connect, etc.)
- Break into short paragraphs for readability (no walls of text)
- Do NOT use em dashes in prose
- Do NOT use generic filler like "I am excited" or "I believe"
- Use clear, direct language — write like a human, not a LinkedIn template

Return ONLY the About section text. No commentary or labels."""

EXPERIENCE_PROMPT = """\
Rewrite the experience section from this resume, optimized for LinkedIn.

RESUME:
{resume}

RULES:
- LinkedIn experience is read differently than a resume — optimize for scanning
- Each role should have a brief 1-2 sentence description of the role/scope, followed by bullet points
- Bullet points should lead with impact and metrics where possible
- Use strong action verbs (Built, Architected, Reduced, Led, Designed, Implemented, Delivered)
- Include relevant keywords that recruiters search for
- Keep each role to 3-5 bullet points max (LinkedIn truncates long descriptions)
- Do NOT invent achievements — only use what's in the resume
- Do NOT use em dashes in descriptions
- Preserve the two separate bbox.digital role entries
- Skip the Aviation career entry — just include the tech roles

Format each role like this:

### [Job Title] at [Company]
[1-2 sentence role description]
- Bullet point 1
- Bullet point 2
...

Return ONLY the experience descriptions. No extra commentary."""

SKILLS_PROMPT = """\
Generate an optimized LinkedIn Skills list based on this resume.

RESUME:
{resume}

RULES:
- LinkedIn allows up to 50 skills — provide 25-30 of the strongest
- Order by relevance and market demand (most important first)
- Include both specific technologies AND broader competencies
- Mix hard skills (React, TypeScript) with soft skills (Technical Leadership, Client Communication)
- Include skills that recruiters commonly search for in senior dev roles
- Do NOT add skills the candidate doesn't demonstrate in their resume
- Group them by category for easy review

Format:

**Top Skills (pin these):**
1. Skill
2. Skill
3. Skill
4. Skill
5. Skill

**Technical Skills:**
- Skill 1
- Skill 2
...

**Tools & Platforms:**
- Skill 1
...

**Professional Skills:**
- Skill 1
...

Return ONLY the skills list. No extra commentary."""


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        print(f"Config file not found: {config_path}")
        raise FileNotFoundError(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_api_key() -> str | None:
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


def optimize_section(client: Anthropic, model: str, resume: str, section: str, temperature: float) -> str:
    prompts = {
        "headline": HEADLINE_PROMPT,
        "about": ABOUT_PROMPT,
        "experience": EXPERIENCE_PROMPT,
        "skills": SKILLS_PROMPT,
    }

    prompt = prompts[section].format(resume=resume)

    max_tokens_map = {
        "headline": 800,
        "about": 1500,
        "experience": 2500,
        "skills": 1500,
    }

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens_map[section],
        temperature=temperature,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def save_output(section: str, content: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    filename = f"linkedin_{section}.md"
    path = os.path.join(output_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# LinkedIn {section.title()} — Optimized\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("---\n\n")
        f.write(content)
    return path


def run_interactive(client: Anthropic, model: str, resume: str, temperature: float, output_dir: str) -> None:
    print("\n  LinkedIn Profile Optimizer")
    print("  " + "=" * 40)
    print("  Which section would you like to optimize?\n")
    print("  1. Headline")
    print("  2. About / Bio")
    print("  3. Experience descriptions")
    print("  4. Skills")
    print("  5. All sections")
    print("  q. Quit\n")

    choice = input("  Choose [1-5, q]: ").strip().lower()

    choice_map = {"1": "headline", "2": "about", "3": "experience", "4": "skills", "5": "all"}

    if choice == "q":
        print("  Cancelled.")
        return

    if choice not in choice_map:
        print(f"  Invalid choice: {choice}")
        return

    selected = choice_map[choice]
    sections = SECTIONS if selected == "all" else [selected]

    for section in sections:
        print(f"\n  Optimizing {section}...")
        content = optimize_section(client, model, resume, section, temperature)
        path = save_output(section, content, output_dir)
        print(f"  Saved: {path}")
        print(f"\n{'='*60}")
        print(content)
        print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize LinkedIn profile sections using AI.")
    parser.add_argument("--section", "-s", choices=SECTIONS + ["all"], default=None,
                        help="Section to optimize (default: interactive menu)")
    parser.add_argument("--output-dir", "-d", default=None,
                        help="Output directory (default: linkedin_<timestamp>)")
    parser.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH,
                        help=f"Config YAML (default: {DEFAULT_CONFIG_PATH})")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        return

    try:
        resume = load_base_resume()
    except FileNotFoundError:
        return

    api_key = get_api_key()
    if not api_key:
        print("ANTHROPIC_API_KEY not found.")
        print("  Set it as an environment variable or create a .env file.")
        return

    model = config.get("model", "claude-sonnet-4-20250514")
    temperature = config.get("temperature", 1.0)
    output_dir = args.output_dir or f"linkedin_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"

    print(f"  LinkedIn Profile Optimizer")
    print(f"  Model:       {model}")
    print(f"  Temperature: {temperature}")
    print(f"  Output dir:  {output_dir}")

    client = Anthropic(api_key=api_key)

    if args.section:
        sections = SECTIONS if args.section == "all" else [args.section]
        for section in sections:
            print(f"\n  Optimizing {section}...")
            content = optimize_section(client, model, resume, section, temperature)
            path = save_output(section, content, output_dir)
            print(f"  Saved: {path}")
            print(f"\n{'='*60}")
            print(content)
            print(f"{'='*60}\n")
    else:
        run_interactive(client, model, resume, temperature, output_dir)

    print(f"\n  Done! Results saved to {output_dir}/")


if __name__ == "__main__":
    main()
