# OCR Rumors — Hebrew Play Audio Generator

A tool for **amateur theatre actors** to memorise their roles. It takes scanned screenplay pages, extracts the dialogue with AI, and produces a narrated audio file where each character speaks in a distinct voice — so you can listen to the full play and hear your cues naturally.

Built with [Claude Code](https://claude.ai/claude-code) (vibe coding — no manual coding required).

---

## What it does

**Stage 1 — OCR** (`convert.py`)
Reads PNG images of screenplay pages, sends each to Google Gemini 2.0 Flash vision API, extracts character names and dialogue, and writes a Hebrew RTL HTML table (`screenplay_output.html`).

**Stage 2 — TTS** (`play_tts.py`)
Reads a plain-text play file, generates per-character MP3 audio via ElevenLabs (model `eleven_v3`, supports Hebrew), and produces:

| Output file | Use |
|---|---|
| `distr/play_audio.mp3` | Full concatenated play audio |
| `distr/play.smil` | SMIL timing file — open with [Thorium Reader](https://thorium.edrlab.org/) (free DAISY player) |
| `distr/play_player.html` | Open in any browser: click any line to seek, search text |

The HTML player highlights the current line during playback and lets you mute individual characters — useful when you want to practice your own role while the rest of the cast plays back.

---

## Cost

| Service | Plan | Characters included | Monthly cost |
|---|---|---|---|
| ElevenLabs | Starter | 100,000 characters | **$11 / month** |
| Google Gemini | Free tier | generous free quota | **$0** (for typical use) |

A typical full-length play is roughly 50,000–80,000 characters, so the $11/month ElevenLabs plan comfortably covers one or two productions. Audio segments are cached locally — re-runs only charge for new or changed lines.

---

## Setup

### Prerequisites

- Python 3.12 via [Miniforge](https://github.com/conda-forge/miniforge) or any Python 3.10+
- `ffmpeg` (required by pydub for MP3 encoding)

```bash
brew install ffmpeg   # macOS
```

### Install dependencies

```bash
python3.12 -m venv venv
source venv/bin/activate

# OCR pipeline
pip install google-genai pillow

# TTS pipeline
pip install elevenlabs pydub
```

### API keys

Create a `.env` file in the project root:

```
GEMINI_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here
```

Load before running:

```bash
export $(cat .env | xargs)
```

---

## Usage

### Stage 1 — OCR: images to text

Put your screenplay PNG images in `./pages/` then run:

```bash
python convert.py
```

Output: `screenplay_output.html` — review it and copy the dialogue into a plain-text file for Stage 2.

### Stage 2 — TTS: text to audio

Your input file must follow this format:

```
[Character Name]
Dialogue text here.
[Another Character]
More dialogue. (stage directions in parentheses are stripped)
```

**First run** — generates `voices.json` with auto-assigned voices:

```bash
python play_tts.py input.txt
```

Open `voices.json` and assign the right `voice_id` to each character from the `_available_voices` list. Pick voices that match the characters' gender, age, and personality.

**Second run** — generates audio and player:

```bash
python play_tts.py input.txt
```

#### Additional commands

```bash
# Generate only a range of lines (resumes from cache)
python play_tts.py input.txt --start 10 --end 50

# Assemble output files from already-generated cache (no new API calls)
python play_tts.py input.txt combine

# Add voices for newly added characters without regenerating existing ones
python play_tts.py input.txt update-voices

# Wipe the segment cache and start fresh
python play_tts.py input.txt --clear-cache
```

Generation is resumable — each dialogue line is cached individually in `./cache/`. If the run is interrupted, re-running picks up where it left off.

---

## Project structure

```
ocrrumors/
├── convert.py            # Stage 1: OCR images → HTML
├── play_tts.py           # Stage 2: text → MP3 + SMIL + HTML player
├── player_template.html  # HTML player template
├── voices.json           # Per-character voice config (auto-generated)
├── pages/                # Source PNG images
├── cache/                # Per-line MP3 cache (auto-generated)
└── distr/                # Final output files (auto-generated)
```
