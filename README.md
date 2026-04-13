# Wingman

AI-powered dating chat assistant. Reads your screen, listens to your voice, and generates reply suggestions in real time.

## How it works

1. **Screen capture** grabs the chat window at ~1 FPS and detects when content changes
2. **Apple Vision OCR** extracts message text and determines who sent each message (left = them, right = you)
3. **Transcript builder** deduplicates overlapping text across frames and maintains a rolling conversation history
4. **Gemini 3.1 Flash Live** (WebSocket) streams screen frames + your microphone audio for real-time awareness and voice commands
5. **Gemini 3.1 Pro** receives the structured transcript and generates 5 reply options on demand
6. **Web UI** shows the live transcript and reply cards — click any card to copy to clipboard

## Setup

### Requirements

- macOS (for Apple Vision OCR)
- Python 3.11+
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/)
- PortAudio (`brew install portaudio`) for microphone access

### Install

```bash
# Clone and enter the project
cd "WINGMAN OG"

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your API key
cp .env.example .env
# Edit .env and paste your GEMINI_API_KEY
```

### Grant permissions

macOS will ask for **Screen Recording** and **Microphone** permission the first time you run.

## Usage

### Run the full system (server + all engines)

```bash
python -m server.app
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

### Capture a specific screen region

If you only want to capture part of the screen (e.g. the chat window):

```bash
python -m wingman.main --left 100 --top 200 --width 800 --height 600
```

### Controls

- **Style dropdown** — set the reply tone (playful, flirty, warm, direct, etc.)
- **Generate Replies** button — manually trigger reply generation
- **Voice** — speak naturally: "make it flirty", "keep it short", "give me options"
- **Click any reply card** to copy it to clipboard

## Architecture

```
Screen → Change Detection → Apple Vision OCR → Transcript Builder
                ↓                                       ↓
       Gemini Flash Live ←──── mic audio        Gemini 3.1 Pro
       (voice commands)                     (reply generation)
                                                       ↓
                                                   Web UI
                                              (reply cards)
```

## Cost

With the hybrid OCR + Live API approach, typical usage costs **$0.20–0.25 per session** (10 min). Monthly cost at moderate use: **$10–30**.
