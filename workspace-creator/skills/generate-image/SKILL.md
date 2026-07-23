# Skill: generate-image

## What This Skill Does
Generates a photorealistic editorial feature image using **Vertex Gemini Flash Lite Image** via the local **Bifrost** gateway (primary), with **HF FLUX.1 Schnell** fallback, saves it locally, and optionally watermarks it with the brand logo.

## How to Invoke

```bash
bash ~/.openclaw-backlink/workspace-creator/skills/generate-image/generate.sh "<YOUR PROMPT>"
```

**Example:**
```bash
bash ~/.openclaw-backlink/workspace-creator/skills/generate-image/generate.sh "Photorealistic 3D gold Bitcoin coin on black reflective surface, warm studio lighting, red candlestick chart softly glowing in background, cinematic crypto editorial, photorealistic, studio lighting, dark background, sharp focus"
```

## Environment Variables (optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `BIFROST_BASE_URL` | `http://192.168.32.1:8888/v1` | Bifrost OpenAI-compatible API base |
| `IMAGE_MODEL` | `vertex/gemini-3.1-flash-lite-image` | Primary (~$0.000034/image) |
| `IMAGE_MODEL_FALLBACK` | `huggingface/hf-inference/black-forest-labs/FLUX.1-schnell` | Fallback if primary fails |
| `OUTPUT_PATH` | `/tmp/crypto-feature.jpg` | Save path (orchestrator sets per run) |
| `PROJECT_CONFIG` | — | Project JSON path (resolves `creator.logo_path`) |
| `PROJECT_SLUG` | `crypto` | Per-run slug for result/error file names |
| `STAMP_LOGO` | `1` | Set `0` to skip logo composite |

## Return Values

| Exit Code | Meaning | Where to Read Result |
|-----------|---------|----------------------|
| `0` (success) | Image generated, watermarked, saved | `cat /tmp/<slug>-image-result.txt` |
| `1` (failure) | Something went wrong | `cat /tmp/<slug>-image-error.log` |

## What the Script Handles Automatically
- Bifrost `POST /v1/images/generations` → Vertex Gemini Flash Lite Image (primary), HF FLUX fallback
- Primary then fallback per retry round (up to 3 rounds)
- Editorial negative constraints appended to prompt (no text overlay/humans/clipart)
- Base64 decode, resize to 1920×1080 (16:9), optional logo stamp
- Symlink-safe write via `OUTPUT_PATH` (default `/tmp/crypto-feature.jpg`)
- Per-project logo stamp from `PROJECT_CONFIG` → `creator.logo_path` (100px, bottom-right)
- Writes `${OUTPUT_PATH}.watermarked` marker (required by `publish.sh`)
- **Post-stamp validation:** final JPEG must be ≥40 KB with valid JPEG magic bytes
- Expect **~5–10 seconds** per successful generation

## What YOU Must Do (Your Only Job)
1. Read the article title and topic from the message you received.
2. Craft an **article-specific** editorial prompt using the rules in your SOUL.md.
3. Call this script with that prompt.
4. Read the result:
   - If exit code 0: Return `cat /tmp/image-result.txt`
   - If exit code 1: Return `IMAGE_FAILED: ` + `cat /tmp/image-error.log`

## Important Notes
- The prompt must be under 1000 characters.
- Do NOT request readable text overlays, headlines, or typography in the image — describe symbols and shapes instead.
- Do NOT call Bifrost or any image API directly — always use this script.
