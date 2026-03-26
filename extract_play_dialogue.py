#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple

from docx import Document

# Character -> actor mapping supplied by the user.
CHAR_TO_ACTOR: Dict[str, str] = OrderedDict([
    ("קן", "מורן"),
    ("כריס", "אורנה"),
    ("לני", "איליה"),
    ("קלייר", "אורלי"),
    ("ארני", "רונן"),
    ("קוקי", "זויה"),
    ("גלן", "מיכל"),
    ("קאסי", "איילת"),
    ("וולץ'", "שחקן אורח"),
    ("אמנדה", "איילת"),
])


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\t", " ")
    text = re.sub(r"[ ]+", " ", text)
    # Keep explicit line breaks inside a paragraph if they exist.
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def split_leading_bold_name(paragraph, valid_names: Iterable[str]) -> Tuple[Optional[str], str]:
    """Return (speaker_name, remainder_text).

    Speaker is recognized only if the paragraph starts with one or more bold runs
    that spell one of the known names. This avoids false positives in normal text.
    """
    full_text = paragraph.text or ""
    if not full_text.strip():
        return None, ""

    leading = ""
    pos = 0
    started = False

    for run in paragraph.runs:
        run_text = run.text or ""
        if not run_text:
            continue

        if not started:
            if run_text.strip() == "":
                pos += len(run_text)
                continue
            started = True

        if run.bold:
            leading += run_text
            pos += len(run_text)
            continue

        break

    candidate = normalize_text(leading)
    if not candidate:
        return None, normalize_text(full_text)

    # Prefer longer names first, so "השוטרת אמנדה" beats "השוטר"-like prefixes.
    for name in sorted(valid_names, key=len, reverse=True):
        if candidate == name:
            remainder = normalize_text(full_text[pos:])
            return name, remainder

    return None, normalize_text(full_text)


def extract_blocks(docx_path: str, name_mode: str) -> List[Tuple[str, str]]:
    document = Document(docx_path)
    blocks: List[Tuple[str, List[str]]] = []
    current_speaker: Optional[str] = None

    def display_name(character: str) -> str:
        if name_mode == "actor":
            return CHAR_TO_ACTOR.get(character, character)
        if name_mode == "both":
            actor = CHAR_TO_ACTOR.get(character)
            return f"{character} - {actor}" if actor else character
        return character

    for paragraph in document.paragraphs:
        speaker, text = split_leading_bold_name(paragraph, CHAR_TO_ACTOR.keys())
        if not text and speaker is None:
            continue

        if speaker is not None:
            current_speaker = display_name(speaker)
            blocks.append((current_speaker, []))
            if text:
                blocks[-1][1].append(text)
            continue

        if current_speaker is None:
            # No speaker yet; preserve orphaned stage directions in a neutral block.
            current_speaker = "STAGE"
            blocks.append((current_speaker, []))

        if text:
            blocks[-1][1].append(text)

    return [(speaker, "\n".join(lines).strip()) for speaker, lines in blocks if lines]


def write_output(blocks: List[Tuple[str, str]], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for i, (speaker, text) in enumerate(blocks):
            if i:
                f.write("\n\n")
            f.write(f"[{speaker}]\n")
            f.write(text)
            f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract dialogue blocks from a Word play script into a plain text file."
    )
    parser.add_argument("input_docx", help="Path to the input .docx file")
    parser.add_argument("output_txt", help="Path to the output .txt file")
    parser.add_argument(
        "--names",
        choices=["character", "actor", "both"],
        default="character",
        help="What to put in [brackets]: character name, actor name, or both",
    )
    args = parser.parse_args()

    blocks = extract_blocks(args.input_docx, args.names)
    write_output(blocks, args.output_txt)


if __name__ == "__main__":
    main()
