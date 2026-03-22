#!/usr/bin/env python3
"""
play_tts.py — Hebrew play TTS generator using ElevenLabs API.

Usage:
    python play_tts.py input.txt

First run (no voices.json):
    Fetches available voices, generates voices.json → edit it, then re-run.

Second run (voices.json exists):
    Generates play_audio.mp3, play.smil, play_player.html
"""

import json
import os
import re
import sys
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

# ── Dependencies check ──────────────────────────────────────────────────────

try:
    from elevenlabs import ElevenLabs
    from elevenlabs.types import VoiceSettings
except ImportError:
    sys.exit("Missing dependency: pip install elevenlabs")

try:
    from pydub import AudioSegment
except ImportError:
    sys.exit("Missing dependency: pip install pydub  (also needs ffmpeg)")


# ── Constants ───────────────────────────────────────────────────────────────

MODEL_ID = "eleven_multilingual_v2"
SILENCE_BETWEEN_SPEAKERS_MS = 400
SILENCE_BETWEEN_LINES_MS = 150
VOICES_FILE = "voices.json"
AUDIO_FILE = "play_audio.mp3"
SMIL_FILE = "play.smil"
HTML_FILE = "play_player.html"

# 8 distinct colors for characters (RTL-friendly palette)
CHARACTER_COLORS = [
    "#c0392b", "#2980b9", "#27ae60", "#8e44ad",
    "#e67e22", "#16a085", "#d35400", "#2c3e50",
]

# Default voice settings variations to differentiate characters
VOICE_PRESETS = [
    {"stability": 0.55, "similarity_boost": 0.80, "style": 0.20, "speed": 1.00},
    {"stability": 0.35, "similarity_boost": 0.75, "style": 0.40, "speed": 0.95},
    {"stability": 0.70, "similarity_boost": 0.90, "style": 0.10, "speed": 1.05},
    {"stability": 0.45, "similarity_boost": 0.65, "style": 0.50, "speed": 0.90},
    {"stability": 0.60, "similarity_boost": 0.85, "style": 0.30, "speed": 1.10},
    {"stability": 0.30, "similarity_boost": 0.70, "style": 0.55, "speed": 0.85},
    {"stability": 0.75, "similarity_boost": 0.95, "style": 0.05, "speed": 1.15},
    {"stability": 0.50, "similarity_boost": 0.60, "style": 0.45, "speed": 1.00},
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
            "Adjust stability (0.0-1.0), similarity_boost (0.0-1.0), "
            "style (0.0-1.0), and speed (0.7-1.3) to differentiate voices. "
            "Available voices are listed in _available_voices."
        ),
        "_available_voices": all_voices,
        "characters": {},
    }

    # Auto-assign voices cycling through available ones
    for i, character in enumerate(characters):
        voice = all_voices[i % len(all_voices)]
        preset = VOICE_PRESETS[i % len(VOICE_PRESETS)]
        config["characters"][character] = {
            "voice_id": voice["voice_id"],
            "voice_name": voice["name"],
            **preset,
        }

    return config


def tts_segment(client: ElevenLabs, text: str, char_config: dict) -> bytes:
    """Call ElevenLabs TTS and return MP3 bytes."""
    settings = VoiceSettings(
        stability=char_config.get("stability", 0.55),
        similarity_boost=char_config.get("similarity_boost", 0.80),
        style=char_config.get("style", 0.20),
        speed=char_config.get("speed", 1.00),
    )
    audio_iter = client.text_to_speech.convert(
        voice_id=char_config["voice_id"],
        text=text,
        model_id=MODEL_ID,
        voice_settings=settings,
    )
    return b"".join(audio_iter)


# ── Audio assembly ──────────────────────────────────────────────────────────

def ms_to_smil_time(ms: int) -> str:
    return f"{ms / 1000:.3f}s"


def build_audio(segments: list[dict], voices_config: dict) -> tuple[AudioSegment, list[dict]]:
    """
    Generate TTS for each segment and concatenate.
    Returns (full_audio, segments_with_timing).
    """
    client = get_client()
    char_configs = voices_config["characters"]
    silence_between = AudioSegment.silent(duration=SILENCE_BETWEEN_SPEAKERS_MS)
    silence_inline = AudioSegment.silent(duration=SILENCE_BETWEEN_LINES_MS)

    full_audio = AudioSegment.empty()
    prev_character = None
    timed_segments = []

    total = len(segments)
    for idx, seg in enumerate(segments, 1):
        char = seg["character"]
        text = seg["clean_text"]

        if char not in char_configs:
            print(f"  WARNING: No voice config for '{char}', skipping segment.")
            continue

        print(f"  [{idx}/{total}] {char}: {text[:60]}{'...' if len(text) > 60 else ''}")

        # Add gap between speakers
        if prev_character is not None:
            if prev_character != char:
                full_audio += silence_between
            else:
                full_audio += silence_inline

        start_ms = len(full_audio)

        try:
            mp3_bytes = tts_segment(client, text, char_configs[char])
            audio_seg = AudioSegment.from_mp3(BytesIO(mp3_bytes))
            full_audio += audio_seg
        except Exception as e:
            print(f"  ERROR generating audio for segment {seg['line_id']}: {e}")
            full_audio += AudioSegment.silent(duration=500)

        end_ms = len(full_audio)
        timed_segments.append({**seg, "start_ms": start_ms, "end_ms": end_ms})
        prev_character = char

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

def generate_html(timed_segments: list[dict], characters: list[str]) -> str:
    char_color = {char: CHARACTER_COLORS[i % len(CHARACTER_COLORS)]
                  for i, char in enumerate(characters)}

    lines_html = []
    for seg in timed_segments:
        color = char_color.get(seg["character"], "#333")
        char_display = seg["character"]
        text = seg["raw_text"]  # Show original text (with stage directions) for readability
        start = seg["start_ms"] / 1000
        end = seg["end_ms"] / 1000
        lines_html.append(
            f'<div class="line" id="{seg["line_id"]}" '
            f'data-start="{start:.3f}" data-end="{end:.3f}" '
            f'onclick="seekTo({start:.3f})">'
            f'<span class="char" style="color:{color}">{char_display}</span>'
            f'<span class="text">{text}</span>'
            f'</div>'
        )

    legend_items = "".join(
        f'<span class="legend-item" style="border-color:{char_color[c]};color:{char_color[c]}">{c}</span>'
        for c in characters
    )

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>מחזה — נגן</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Arial, sans-serif;
    background: #1a1a2e;
    color: #e0e0e0;
    direction: rtl;
  }}
  #player-bar {{
    position: sticky;
    top: 0;
    z-index: 100;
    background: #16213e;
    padding: 12px 20px;
    border-bottom: 1px solid #0f3460;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  audio {{
    width: 100%;
    height: 40px;
    direction: ltr;
  }}
  #search-row {{
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }}
  #search-box {{
    flex: 1;
    min-width: 200px;
    padding: 8px 12px;
    border-radius: 6px;
    border: 1px solid #0f3460;
    background: #0f3460;
    color: #fff;
    font-size: 15px;
    direction: rtl;
  }}
  #search-box::placeholder {{ color: #888; }}
  #search-info {{
    font-size: 13px;
    color: #aaa;
    white-space: nowrap;
  }}
  #legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .legend-item {{
    font-size: 12px;
    padding: 2px 8px;
    border: 1.5px solid;
    border-radius: 12px;
    cursor: pointer;
  }}
  #transcript {{
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
  }}
  .line {{
    display: flex;
    align-items: baseline;
    gap: 14px;
    padding: 8px 12px;
    border-radius: 6px;
    cursor: pointer;
    transition: background 0.15s;
    line-height: 1.6;
  }}
  .line:hover {{ background: #16213e; }}
  .line.active {{ background: #0f3460; border-right: 3px solid #e94560; }}
  .line.highlight {{ background: #2a2a00; }}
  .char {{
    min-width: 110px;
    max-width: 110px;
    font-weight: bold;
    font-size: 14px;
    text-align: right;
    flex-shrink: 0;
  }}
  .text {{
    flex: 1;
    font-size: 16px;
  }}
  mark {{
    background: #f0c040;
    color: #000;
    border-radius: 2px;
    padding: 0 1px;
  }}
</style>
</head>
<body>

<div id="player-bar">
  <audio id="audio" controls src="{AUDIO_FILE}"></audio>
  <div id="search-row">
    <input id="search-box" type="text" placeholder="חיפוש בטקסט..." autocomplete="off">
    <span id="search-info"></span>
  </div>
  <div id="legend">{legend_items}</div>
</div>

<div id="transcript">
{''.join(lines_html)}
</div>

<script>
const audio = document.getElementById('audio');
const searchBox = document.getElementById('search-box');
const searchInfo = document.getElementById('search-info');
const lines = Array.from(document.querySelectorAll('.line'));
let searchResults = [];
let searchIdx = 0;

function seekTo(t) {{
  audio.currentTime = t;
  audio.play();
}}

// Highlight active line during playback
audio.addEventListener('timeupdate', () => {{
  const t = audio.currentTime;
  lines.forEach(el => {{
    const start = parseFloat(el.dataset.start);
    const end = parseFloat(el.dataset.end);
    if (t >= start && t < end) {{
      el.classList.add('active');
      if (!isInViewport(el)) {{
        el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
      }}
    }} else {{
      el.classList.remove('active');
    }}
  }});
}});

function isInViewport(el) {{
  const r = el.getBoundingClientRect();
  return r.top >= 80 && r.bottom <= window.innerHeight;
}}

// Search
searchBox.addEventListener('input', () => {{
  clearHighlights();
  const q = searchBox.value.trim();
  if (!q) {{ searchInfo.textContent = ''; return; }}

  searchResults = [];
  const re = new RegExp(q.replace(/[.*+?^${{}}()|[\]\\\\]/g, '\\\\$&'), 'gi');

  lines.forEach(el => {{
    const textSpan = el.querySelector('.text');
    const orig = textSpan.textContent;
    if (re.test(orig)) {{
      textSpan.innerHTML = orig.replace(re, m => `<mark>${{m}}</mark>`);
      searchResults.push(el);
    }}
    re.lastIndex = 0;
  }});

  if (searchResults.length > 0) {{
    searchIdx = 0;
    scrollToResult();
    searchInfo.textContent = `${{searchIdx + 1}} / ${{searchResults.length}}`;
  }} else {{
    searchInfo.textContent = 'לא נמצא';
  }}
}});

searchBox.addEventListener('keydown', e => {{
  if (searchResults.length === 0) return;
  if (e.key === 'Enter') {{
    if (e.shiftKey) {{
      searchIdx = (searchIdx - 1 + searchResults.length) % searchResults.length;
    }} else {{
      searchIdx = (searchIdx + 1) % searchResults.length;
    }}
    scrollToResult();
    searchInfo.textContent = `${{searchIdx + 1}} / ${{searchResults.length}}`;
  }}
}});

function scrollToResult() {{
  searchResults[searchIdx].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  searchResults[searchIdx].classList.add('highlight');
  setTimeout(() => searchResults[searchIdx] && searchResults[searchIdx].classList.remove('highlight'), 1200);
}}

function clearHighlights() {{
  lines.forEach(el => {{
    const textSpan = el.querySelector('.text');
    textSpan.innerHTML = textSpan.textContent;
  }});
}}

// Legend click → filter/jump to first line of that character
document.querySelectorAll('.legend-item').forEach(item => {{
  item.addEventListener('click', () => {{
    const char = item.textContent;
    const first = lines.find(l => l.querySelector('.char').textContent === char);
    if (first) first.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
  }});
}});
</script>
</body>
</html>
"""


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} input.txt")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        sys.exit(f"File not found: {input_path}")

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
        print("  → Open it, assign voice IDs and adjust settings for each character.")
        print(f"  → Then re-run: python {sys.argv[0]} {sys.argv[1]}")
        print("\nQuick reference — voice parameters:")
        print("  stability:       0.3 (expressive) – 0.8 (consistent)")
        print("  similarity_boost:0.5 (varied) – 0.95 (close to original)")
        print("  style:           0.0 (neutral) – 0.6 (dramatic)")
        print("  speed:           0.8 (slow) – 1.2 (fast)")
        return

    # ── Second run: generate audio ──────────────────────────────────────────
    voices_config = json.loads(voices_path.read_text(encoding="utf-8"))

    missing = [c for c in characters if c not in voices_config.get("characters", {})]
    if missing:
        print(f"\nWARNING: These characters have no entry in {VOICES_FILE}: {missing}")
        print("Add them to voices.json and re-run, or they will be skipped.")

    print(f"\nGenerating TTS audio for {len(segments)} segments...")
    full_audio, timed_segments = build_audio(segments, voices_config)

    if not timed_segments:
        sys.exit("No audio segments generated. Check voice config and API key.")

    total_duration_s = len(full_audio) / 1000
    print(f"\nTotal audio duration: {total_duration_s:.1f}s ({total_duration_s/60:.1f} min)")

    print(f"Exporting {AUDIO_FILE}...")
    full_audio.export(AUDIO_FILE, format="mp3", bitrate="128k")

    print(f"Writing {SMIL_FILE}...")
    smil_xml = generate_smil(timed_segments)
    Path(SMIL_FILE).write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + smil_xml,
        encoding="utf-8"
    )

    print(f"Writing {HTML_FILE}...")
    html = generate_html(timed_segments, characters)
    Path(HTML_FILE).write_text(html, encoding="utf-8")

    print(f"\n✓ Done!")
    print(f"  {AUDIO_FILE}       — full play audio")
    print(f"  {SMIL_FILE}        — SMIL timing file (use with Thorium Reader)")
    print(f"  {HTML_FILE}  — open in browser for playback + search")


if __name__ == "__main__":
    main()
