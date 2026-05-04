# Muzo Marketing Content Engine

AI-powered viral script + visual generator for the Muzo editor network.
Editors use the web tool to produce ~20 TikTok/Reels/Shorts videos per
day without needing creative judgment on every script.

## What it does

Given a hook image (or none), tonal mode, length, and twist preference,
it produces:

1. **A JSON script** — 10–28 message Instagram DM conversation, paced
   for short-form video, with a marked "Muzo reveal" moment
2. **Rendered PNG frames** — pixel-perfect Instagram DM overlay, one
   frame per bubble-reveal, at 1080×1920 for vertical video
3. **A `manifest.json`** — per-frame durations for timelapse editing

Editors import the frame pack into CapCut, stack over B-roll (NBA
highlights, GTA 5, Minecraft parkour), and post.

## Components

| File | Purpose |
|---|---|
| `corpus.py` | Loads the 28 hand-curated training transcripts |
| `prompts.py` | System prompt + tonal mode definitions + schema |
| `generate.py` | CLI + core generation logic (calls Gemini 3.1 Pro) |
| `render.py` | CLI + Playwright-powered visual renderer |
| `pipeline.py` | One-shot CLI: generate → render in one command |
| `templates/dm.html` | Instagram DM UI (dark mode, purple gradient) |
| `web.py` | FastAPI editor-facing web UI |
| `Dockerfile` | Container image for DO App Platform deployment |
| `requirements.txt` | Python deps for the web app container |

## Tonal modes

| Mode | Tone | Example opener |
|---|---|---|
| `playful_goofball` | Silly / creative metaphors | "okay ocean's 11, what casino are we robbing" |
| `cocky_critic` | Arrogant rating / review | "Face card: ⭐⭐⭐⭐⭐ / Customer service: ⭐" |
| `forward_direct` | Bold sexual energy msg 1 | "Respectfully, I want to ruin your life a little" |
| `smooth_recovery` | Ex / rejection / loyalty-test | "My phone must be broken, no apology notification" |
| `dark_taboo` | Taboo setup (HIGH reach, HIGH ban) | "You look a lil too comfortable in my hoodie 👀" |

Recommended traffic mix: 70% playful, 20% forward, 5% cocky, 5% smooth.
Avoid dark_taboo until you know your distribution platforms tolerate it.

## Local usage (CLI)

```bash
# One-shot: generate + render + open in Finder
python -m marketing.pipeline \
  --mode playful_goofball \
  --opener-bias balanced \
  --length short \
  --random-hook \
  --out ~/Desktop/muzo_demo \
  --open

# Just a script (no render)
python -m marketing.generate --mode cocky_critic --random-hook --variants 3 --out /tmp/scripts

# Just a render (from an existing script JSON)
python -m marketing.render /tmp/scripts/script_*.json --out /tmp/frames
```

## Deploying the editor tool

```bash
# Build the container
docker build -f marketing/Dockerfile -t muzo-editor .

# Run locally (no auth if MUZO_EDITOR_TOKEN unset)
docker run -p 8080:8080 \
  -e GEMINI_API_KEYS="$GEMINI_API_KEYS" \
  muzo-editor

# Deploy to DigitalOcean
doctl apps create --spec .do/editor-app.yaml
```

Before deploy:

1. Generate a shared token: `openssl rand -base64 24`
2. Edit `.do/editor-app.yaml`:
   - Set `MUZO_EDITOR_TOKEN` to the token
   - Set `GEMINI_API_KEYS` to your comma-separated AI Studio keys
3. `doctl apps create --spec .do/editor-app.yaml`
4. Get the app URL from the DO dashboard
5. Share with editors: `https://muzo-editor-xxxx.ondigitalocean.app/?token=<token>`

## Cost (approximate)

| Unit | Cost |
|---|---|
| One script | ~$0.04 (Gemini 3.1 Pro) |
| One render | $0 (local compute) |
| Full pipeline per video | ~$0.04 |
| 100 videos / day | ~$4 / day ≈ $120 / month |
| 1000 videos / day | ~$40 / day ≈ $1200 / month |

Throughput: ~30–60s per script (single-worker FastAPI). Scale horizontally
for more concurrency.
