#!/usr/bin/env python3
"""
play_tts.py — Hebrew play TTS generator using ElevenLabs API.

Usage:
    python play_tts.py input.txt                        # generate all segments (resumes from cache)
    python play_tts.py input.txt --start 10 --end 50    # generate only lines 10–50
    python play_tts.py input.txt combine                 # combine cached segments → output files
    python play_tts.py input.txt --clear-cache           # wipe cache and start fresh

First run (no voices.json):
    Fetches available voices, generates voices.json → edit it, then re-run.

Second run (voices.json exists):
    Generates play_audio.mp3, play.smil, play_player.html
"""

import argparse
import json
import os
import re
import shutil
import sys
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

# ── Dependencies check ──────────────────────────────────────────────────────

try:
    from elevenlabs import ElevenLabs
except ImportError:
    sys.exit("Missing dependency: pip install elevenlabs")

try:
    from pydub import AudioSegment
except ImportError:
    sys.exit("Missing dependency: pip install pydub  (also needs ffmpeg)")


# ── Constants ───────────────────────────────────────────────────────────────

MODEL_ID = "eleven_v3"
SILENCE_BETWEEN_SPEAKERS_MS = 400
SILENCE_BETWEEN_LINES_MS = 150
VOICES_FILE = "voices.json"
AUDIO_FILE = "play_audio.mp3"
SMIL_FILE = "play.smil"
HTML_FILE = "play_player.html"
CACHE_DIR = Path("cache")

# 8 distinct colors for characters (RTL-friendly palette)
CHARACTER_COLORS = [
    "#c0392b", "#2980b9", "#27ae60", "#8e44ad",
    "#e67e22", "#16a085", "#d35400", "#2c3e50",
]


# ── Text parsing ────────────────────────────────────────────────────────────

def strip_stage_directions(text: str) -> str:
    """Remove content inside parentheses (stage directions)."""
    cleaned = re.sub(r'\([^)]*\)', '', text)
    return re.sub(r'\s+', ' ', cleaned).strip()


def parse_play(text: str) -> list[dict]:
    """
    Parse play text with [Character] headers.

    Returns list of:
        {character, raw_text, clean_text, line_id}
    """
    segments = []
    current_character = None
    line_counter = 0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Character header: [Name]
        char_match = re.match(r'^\[(.+?)\]$', line)
        if char_match:
            current_character = char_match.group(1).strip()
            continue

        if current_character is None:
            continue  # Skip lines before first character header

        clean = strip_stage_directions(line)
        if not clean:
            continue  # Skip lines that were pure stage direction

        line_counter += 1
        segments.append({
            "character": current_character,
            "raw_text": line,
            "clean_text": clean,
            "line_id": f"line_{line_counter:04d}",
        })

    return segments


def get_characters(segments: list[dict]) -> list[str]:
    seen = []
    for seg in segments:
        if seg["character"] not in seen:
            seen.append(seg["character"])
    return seen


# ── ElevenLabs helpers ──────────────────────────────────────────────────────

def get_client() -> ElevenLabs:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        sys.exit("Set the ELEVENLABS_API_KEY environment variable.")
    return ElevenLabs(api_key=api_key)


def fetch_voices(client: ElevenLabs) -> list[dict]:
    response = client.voices.get_all()
    return [{"voice_id": v.voice_id, "name": v.name} for v in response.voices]


def generate_voices_config(client: ElevenLabs, characters: list[str]) -> dict:
    """Fetch available voices and build a voices.json config."""
    print("Fetching available voices from ElevenLabs...")
    all_voices = fetch_voices(client)

    if not all_voices:
        sys.exit("No voices returned from ElevenLabs. Check your API key / subscription.")

    print(f"Found {len(all_voices)} voices.")

    config = {
        "_instructions": (
            "Assign a voice_id to each character. "
            "Available voices are listed in _available_voices."
        ),
        "_available_voices": all_voices,
        "characters": {},
    }

    # Auto-assign voices cycling through available ones
    for i, character in enumerate(characters):
        voice = all_voices[i % len(all_voices)]
        config["characters"][character] = {
            "voice_id": voice["voice_id"],
            "voice_name": voice["name"],
        }

    return config


def tts_segment(client: ElevenLabs, text: str, char_config: dict) -> bytes:
    """Call ElevenLabs TTS and return MP3 bytes."""
    audio_iter = client.text_to_speech.convert(
        voice_id=char_config["voice_id"],
        text=text,
        model_id=MODEL_ID,
    )
    return b"".join(audio_iter)


# ── Audio assembly ──────────────────────────────────────────────────────────

def ms_to_smil_time(ms: int) -> str:
    return f"{ms / 1000:.3f}s"


def compute_silence_ms(prev_character: str | None, current_character: str) -> int:
    if prev_character is None:
        return 0
    return SILENCE_BETWEEN_SPEAKERS_MS if prev_character != current_character else SILENCE_BETWEEN_LINES_MS


def build_audio(segments: list[dict], voices_config: dict, start: int = 1, end: int | None = None) -> tuple[AudioSegment, list[dict]]:
    """
    Generate TTS for each segment and concatenate.
    Caches each segment to CACHE_DIR; resumes from cache on restart.
    start/end are 1-based inclusive indices into the full segment list.
    Returns (full_audio, segments_with_timing).
    """
    CACHE_DIR.mkdir(exist_ok=True)

    client = get_client()
    char_configs = voices_config["characters"]

    # Determine which segments to generate
    end_idx = end if end is not None else len(segments)
    segments_to_run = segments[start - 1:end_idx]

    cached_count = sum(1 for s in segments_to_run if (CACHE_DIR / f"{s['line_id']}.mp3").exists())
    print(f"Cache: {cached_count}/{len(segments_to_run)} segments already generated")

    total = len(segments_to_run)
    prev_character = None

    for idx, seg in enumerate(segments_to_run, 1):
        char = seg["character"]
        text = seg["clean_text"]

        if char not in char_configs:
            print(f"  WARNING: No voice config for '{char}', skipping segment.")
            continue

        global_idx = segments.index(seg) + 1
        print(f"  [{idx}/{total}] (#{global_idx}) {char}: {text[:60]}{'...' if len(text) > 60 else ''}")

        silence_ms = compute_silence_ms(prev_character, char)

        cache_mp3 = CACHE_DIR / f"{seg['line_id']}.mp3"
        cache_meta = CACHE_DIR / f"{seg['line_id']}.json"

        if cache_mp3.exists():
            print(f"    [cached]")
        else:
            try:
                mp3_bytes = tts_segment(client, text, char_configs[char])
                cache_mp3.write_bytes(mp3_bytes)
                cache_meta.write_text(json.dumps({
                    "line_id": seg["line_id"],
                    "character": seg["character"],
                    "clean_text": seg["clean_text"],
                    "silence_before_ms": silence_ms,
                }, ensure_ascii=False), encoding="utf-8")
            except Exception as e:
                print(f"    ERROR: {e}")

        prev_character = char

    return combine_from_cache(segments)


def combine_from_cache(segments: list[dict]) -> tuple[AudioSegment, list[dict]]:
    """
    Build full audio and timing data from cached segment files.
    Segments without a cache file are skipped (logged).
    """
    full_audio = AudioSegment.empty()
    timed_segments = []
    prev_character = None

    for seg in segments:
        cache_mp3 = CACHE_DIR / f"{seg['line_id']}.mp3"
        cache_meta = CACHE_DIR / f"{seg['line_id']}.json"

        if not cache_mp3.exists():
            continue  # not yet generated — skip silently

        # Load silence from sidecar if available, else compute from sequence
        if cache_meta.exists():
            meta = json.loads(cache_meta.read_text(encoding="utf-8"))
            silence_ms = meta["silence_before_ms"]
        else:
            silence_ms = compute_silence_ms(prev_character, seg["character"])

        if silence_ms > 0:
            full_audio += AudioSegment.silent(duration=silence_ms)

        start_ms = len(full_audio)
        audio_seg = AudioSegment.from_mp3(BytesIO(cache_mp3.read_bytes()))
        full_audio += audio_seg
        end_ms = len(full_audio)

        timed_segments.append({**seg, "start_ms": start_ms, "end_ms": end_ms})
        prev_character = seg["character"]

    return full_audio, timed_segments


# ── SMIL generation ─────────────────────────────────────────────────────────

def generate_smil(timed_segments: list[dict]) -> str:
    """Generate SMIL 2.0 XML with per-line clip timings."""
    smil = ET.Element("smil", {
        "xmlns": "http://www.w3.org/2001/SMIL20/Language",
        "xmlns:xlink": "http://www.w3.org/1999/xlink",
    })
    body = ET.SubElement(smil, "body")
    seq = ET.SubElement(body, "seq")

    for seg in timed_segments:
        par = ET.SubElement(seq, "par", {"id": seg["line_id"]})
        ET.SubElement(par, "text", {
            "src": f"{HTML_FILE}#{seg['line_id']}",
        })
        ET.SubElement(par, "audio", {
            "src": AUDIO_FILE,
            "clipBegin": ms_to_smil_time(seg["start_ms"]),
            "clipEnd": ms_to_smil_time(seg["end_ms"]),
        })

    ET.indent(smil, space="  ")
    return ET.tostring(smil, encoding="unicode", xml_declaration=False)


# ── HTML player generation ──────────────────────────────────────────────────

TEMPLATE_FILE = "player_template.html"


def generate_html(timed_segments: list[dict], characters: list[str]) -> str:
    char_color = {char: CHARACTER_COLORS[i % len(CHARACTER_COLORS)]
                  for i, char in enumerate(characters)}

    lines_html = "".join(
        f'<div class="line" id="{seg["line_id"]}" '
        f'data-start="{seg["start_ms"] / 1000:.3f}" data-end="{seg["end_ms"] / 1000:.3f}" '
        f'data-char="{seg["character"]}" '
        f'onclick="seekTo({seg["start_ms"] / 1000:.3f})">'
        f'<span class="char" style="color:{char_color.get(seg["character"], "#333")}">{seg["character"]}</span>'
        f'<span class="text">{seg["raw_text"]}</span>'
        f'</div>'
        for seg in timed_segments
    )
    legend_items = "".join(
        f'<span class="legend-item" style="border-color:{char_color[c]};color:{char_color[c]}">{c}</span>'
        for c in characters
    )
    reduce_items = "".join(
        f'<button class="reduce-btn" data-char="{c}" style="border-color:{char_color[c]};color:{char_color[c]}">{c}</button>'
        for c in characters
    )

    template = Path(TEMPLATE_FILE).read_text(encoding="utf-8")
    return (template
            .replace("__AUDIO_SRC__", AUDIO_FILE)
            .replace("__LEGEND_ITEMS__", legend_items)
            .replace("__REDUCE_ITEMS__", reduce_items)
            .replace("__TRANSCRIPT__", lines_html))


# ── Output export ────────────────────────────────────────────────────────────

def export_outputs(full_audio: AudioSegment, timed_segments: list[dict], characters: list[str]):
    if not timed_segments:
        sys.exit("No cached segments found. Run generation first.")

    total_duration_s = len(full_audio) / 1000
    print(f"\nTotal audio duration: {total_duration_s:.1f}s ({total_duration_s/60:.1f} min)")
    print(f"Segments included: {len(timed_segments)}")

    Path("distr").mkdir(exist_ok=True)

    print(f"Exporting {AUDIO_FILE}...")
    full_audio.export(f"distr/{AUDIO_FILE}", format="mp3", bitrate="128k")

    print(f"Writing {SMIL_FILE}...")
    smil_xml = generate_smil(timed_segments)
    Path(f"distr/{SMIL_FILE}").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + smil_xml,
        encoding="utf-8"
    )

    print(f"Writing {HTML_FILE}...")
    html = generate_html(timed_segments, characters)
    Path(f"distr/{HTML_FILE}").write_text(html, encoding="utf-8")

    print(f"\n✓ Done!")
    print(f"  {AUDIO_FILE}       — full play audio")
    print(f"  {SMIL_FILE}        — SMIL timing file (use with Thorium Reader)")
    print(f"  {HTML_FILE}  — open in browser for playback + search")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Hebrew play TTS generator using ElevenLabs API.",
        usage="%(prog)s input.txt [combine] [--start N] [--end N] [--clear-cache]",
    )
    parser.add_argument("input", help="Input play text file")
    parser.add_argument("command", nargs="?", choices=["combine", "update-voices"],
                        help="'combine': assemble output files from cached segments; "
                             "'update-voices': add missing characters to voices.json")
    parser.add_argument("--start", type=int, default=1, metavar="N",
                        help="First segment to generate, 1-based (default: 1)")
    parser.add_argument("--end", type=int, default=None, metavar="N",
                        help="Last segment to generate, 1-based inclusive (default: last)")
    parser.add_argument("--clear-cache", action="store_true",
                        help="Delete all cached segment files and exit")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"File not found: {input_path}")

    if args.clear_cache:
        if CACHE_DIR.exists():
            shutil.rmtree(CACHE_DIR)
            print(f"Cache cleared: {CACHE_DIR}/")
        else:
            print("Cache directory does not exist — nothing to clear.")
        return

    text = input_path.read_text(encoding="utf-8")
    segments = parse_play(text)

    if not segments:
        sys.exit("No dialogue segments found. Check the input format:\n[Character Name]\\nDialogue...")

    characters = get_characters(segments)
    print(f"Found {len(segments)} dialogue segments across {len(characters)} characters:")
    for c in characters:
        count = sum(1 for s in segments if s["character"] == c)
        print(f"  {c}: {count} lines")

    voices_path = Path(VOICES_FILE)

    # ── First run: generate voices config ──────────────────────────────────
    if not voices_path.exists():
        print(f"\nNo {VOICES_FILE} found. Generating voice configuration...")
        client = get_client()
        config = generate_voices_config(client, characters)
        voices_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✓ Created {VOICES_FILE}")
        print("  → Open it and assign a voice_id to each character from _available_voices.")
        print(f"  → Then re-run: python {sys.argv[0]} {args.input}")
        return

    voices_config = json.loads(voices_path.read_text(encoding="utf-8"))

    missing = [c for c in characters if c not in voices_config.get("characters", {})]
    if missing:
        print(f"\nWARNING: These characters have no entry in {VOICES_FILE}: {missing}")
        print("Add them to voices.json and re-run, or they will be skipped.")

    # ── Update-voices mode ──────────────────────────────────────────────────
    if args.command == "update-voices":
        if not voices_path.exists():
            print(f"No {VOICES_FILE} found. Run without a command first to generate it.")
            return
        missing_chars = [c for c in characters if c not in voices_config.get("characters", {})]
        if not missing_chars:
            print(f"All {len(characters)} characters already have voice entries. Nothing to update.")
            return
        print(f"\nAdding {len(missing_chars)} missing character(s) to {VOICES_FILE}: {missing_chars}")
        client = get_client()
        all_voices = voices_config.get("_available_voices") or fetch_voices(client)
        existing_count = len(voices_config.get("characters", {}))
        for i, character in enumerate(missing_chars):
            voice = all_voices[(existing_count + i) % len(all_voices)]
            voices_config["characters"][character] = {
                "voice_id": voice["voice_id"],
                "voice_name": voice["name"],
            }
            print(f"  + {character} → {voice['name']} ({voice['voice_id']})")
        voices_path.write_text(json.dumps(voices_config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✓ {VOICES_FILE} updated. Review new entries and adjust voice_id as needed.")
        return

    # ── Combine mode ────────────────────────────────────────────────────────
    if args.command == "combine":
        print(f"\nCombining cached segments into output files...")
        full_audio, timed_segments = combine_from_cache(segments)
        export_outputs(full_audio, timed_segments, characters)
        return

    # ── Generate mode ───────────────────────────────────────────────────────
    if args.start != 1 or args.end is not None:
        end_display = args.end or len(segments)
        print(f"\nGenerating segments {args.start}–{end_display} of {len(segments)}...")
    else:
        print(f"\nGenerating TTS audio for {len(segments)} segments...")

    full_audio, timed_segments = build_audio(segments, voices_config, start=args.start, end=args.end)

    if not timed_segments:
        print("\nNo segments in cache yet. Generation may have been interrupted before any segment completed.")
        return

    export_outputs(full_audio, timed_segments, characters)


if __name__ == "__main__":
    main()
