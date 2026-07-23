# TOOLS.md - Local Notes

## Image generation (Vertex Imagen 4 via Bifrost)

**Do NOT use `image_generate`.** Use `exec` with the bash skill:

```bash
mkdir -p "$RUN_DIR/content/images" && bash ~/.openclaw-backlink/workspace-bl-content/skills/generate-image/generate.sh "<prompt>" "$RUN_DIR/content/images/name.jpg"
```

Bifrost base URL: `http://172.30.176.1:8888/v1` (set via `BIFROST_BASE_URL` in openclaw.json env).

On success: stdout or `/tmp/image-result.txt` contains the file path.
On failure: `/tmp/image-error.log` has the reason.

Read audit results from spawn message path.
