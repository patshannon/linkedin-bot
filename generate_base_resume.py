"""
Base Resume Generator — Convert base_resume.md to a formatted DOCX.

No AI involved — just converts your base resume directly using the same
formatting logic as the tailored generator.

Usage:
    python generate_base_resume.py
    python generate_base_resume.py --output my_resume.docx
    python generate_base_resume.py --config ai_config.yaml
"""

import argparse
import os

import yaml

from generator import create_resume_docx, load_base_resume


DEFAULT_CONFIG_PATH = "ai_config.yaml"


def load_config(config_path: str) -> dict:
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        raise FileNotFoundError(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a base resume DOCX from base_resume.md.")
    parser.add_argument("--output", "-o", default=None, help="Output file path (default: Patrick_Shannon_Resume.docx)")
    parser.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH, help=f"Config YAML (default: {DEFAULT_CONFIG_PATH})")
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except FileNotFoundError:
        return

    try:
        base_resume = load_base_resume()
    except FileNotFoundError:
        return

    personal = config.get("personal", {})
    name = personal.get("name", "Resume")
    safe_name = name.replace(" ", "_")

    output_path = args.output or f"{safe_name}_Resume.docx"

    print(f"📄 Generating base resume...")
    print(f"   Config:  {args.config}")
    print(f"   Output:  {output_path}")

    create_resume_docx(base_resume, config, "", "", output_path)

    print(f"✅ Saved: {output_path}")


if __name__ == "__main__":
    main()
