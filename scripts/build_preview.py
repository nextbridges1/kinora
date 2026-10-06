"""Builds a static, server-free copy of the interface in preview/ for sharing as a link.

The preview uses placeholder replies (clearly labelled) and never contacts OpenAI.
Companion data comes from config/companions.json, minus the private instructions.

Usage:  python scripts/build_preview.py
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.companions import public_list  # noqa: E402
from server.config import load_settings  # noqa: E402

WEB = ROOT / "web"
OUT = ROOT / "preview"


def section(html: str, name: str) -> str:
    match = re.search(rf"<!--{name}-->(.*?)<!--/{name}-->", html, re.S)
    return match.group(1).strip()


def main() -> None:
    s = load_settings()
    html = (WEB / "index.html").read_text(encoding="utf-8")
    head = section(html, "HEAD").replace('<link rel="stylesheet" href="styles.css">', "")
    head = re.sub(r'<link rel="preconnect"[^>]*>\s*', "", head)
    data = {
        "companions": public_list(),
        "limits": {"max_message_chars": s.max_message_chars, "max_recording_seconds": s.max_recording_seconds,
                   "max_audio_bytes": s.max_audio_bytes},
    }
    page = "\n".join([
        head,
        "<style>\n" + (WEB / "styles.css").read_text(encoding="utf-8") + "\n</style>",
        section(html, "BODY"),
        "<script>window.KINORA_PREVIEW = " + json.dumps(data) + ";</script>",
        "<script>\n" + (WEB / "app.js").read_text(encoding="utf-8") + "\n</script>",
    ])
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "portraits").mkdir(parents=True)
    (OUT / "kinora.html").write_text(page, encoding="utf-8")
    for svg in (WEB / "portraits").glob("*.svg"):
        shutil.copy(svg, OUT / "portraits" / svg.name)
    print(f"Preview written to {OUT / 'kinora.html'}")


if __name__ == "__main__":
    main()
