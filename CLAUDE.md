# ocrrumors — Project Context

## What this project does

Two-stage Hebrew screenplay pipeline:

1. **OCR stage** (`convert.py`) — reads PNG page images from `./pages`, sends each to Gemini 2.0 Flash vision API, extracts character names + dialogue, writes an HTML table (`screenplay_output.html`).

2. **TTS stage** (`play_tts.py`) — reads a plain-text play file in `[Character]\nDialogue` format, generates per-character MP3 audio via ElevenLabs, and produces three output files: `play_audio.mp3`, `play.smil`, `play_player.html`.

## Environment

- Python 3.12 via Miniforge3 (`/Users/Ilya.Novojilov/Miniforge3/bin/python3.12`)
- Virtualenv at `./venv` — activate with `source venv/bin/activate`
- No `requirements.txt` — install manually (see below)

## API keys (env vars)

| Variable | Used by |
|---|---|
| `GEMINI_API_KEY` | `convert.py` (Google Gemini) |
| `ELEVENLABS_API_KEY` | `play_tts.py` (ElevenLabs TTS) |

Keys are in `.env` (not committed). Load with `export $(cat .env | xargs)` or use `python-dotenv`.

## Dependencies

```bash
# OCR pipeline
pip install google-genai pillow

# TTS pipeline
pip install elevenlabs pydub
brew install ffmpeg   # required by pydub for MP3 encoding
```

## Key files

| File | Purpose |
|---|---|
| `convert.py` | OCR: images → HTML table |
| `play_tts.py` | TTS: play text → MP3 + SMIL + HTML player |
| `voices.json` | Per-character voice config (auto-generated on first run of play_tts.py) |
| `screenplay_output.html` | Full OCR output (Hebrew, RTL) |
| `pages/` | Source PNG images (pages 20–61) |
| `pages/all/` | Complete image set (pages 2–61) |

## play_tts.py — input format

```
[Character Name]
dialogue text (stage direction stripped) more text
[Another Character]
...
```

- `[Name]` alone on a line = speaker change
- Text in `(parentheses)` = stage directions, stripped before TTS
- ElevenLabs model: `eleven_v3` (70+ languages including Hebrew)

## play_tts.py — two-phase workflow

```bash
# Phase 1: generates voices.json with 8 auto-assigned voices
python play_tts.py input.txt

# Edit voices.json — swap voice_id, tune stability/speed/style per character

# Phase 2: generates play_audio.mp3 + play.smil + play_player.html
python play_tts.py input.txt
```

## Output files from play_tts.py

| File | Use |
|---|---|
| `play_audio.mp3` | Full concatenated audio |
| `play.smil` | SMIL timing — open with Thorium Reader (free DAISY player) |
| `play_player.html` | Open in any browser: click lines to seek, search text |

## Language notes

- All screenplay content is Hebrew (RTL)
- HTML outputs use `dir="rtl" lang="he"`
- OCR prompt explicitly instructs Gemini not to translate
