"""Fetch the GitHub Release dataset zip and extract it into the runtime layout.

Used by Render (or any deployment) at build time to pull the dataset/models
that are excluded from the git repo.

Behavior:
  - Skip download if every required runtime file already exists.
  - Download zip from $HACCP_RELEASE_URL (default: v1.0 release URL).
  - Extract into:
        csv/*               -> haccp_dashboard/
        models/cnn/*        -> haccp_dashboard/CNN 파일/
        models/sensor/*     -> haccp_dashboard/models/
        images/<class>/*    -> haccp_dashboard/resize_640 x 360/<class>/

Env vars:
  HACCP_RELEASE_URL  override the zip URL
  HACCP_SKIP_FETCH   if set ("1"/"true"), skip everything (useful for local dev)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "haccp_dashboard"

DEFAULT_RELEASE_URL = (
    "https://github.com/juhan9437-dotcom/haccp_dashboard/"
    "releases/download/v1.0/haccp_dashboard_release_v1.zip"
)

# Required files to consider the runtime "ready" (skip download if all exist).
REQUIRED_FILES = [
    PKG_ROOT / "batch_150_contaminated_onlylabel_final_v4.csv",
    PKG_ROOT / "sample_inference_input_19f.csv",
    PKG_ROOT / "CNN 파일" / "mobilenetv2_final_full.pt",
    PKG_ROOT / "models" / "track1_inception_fold5.keras",
    PKG_ROOT / "models" / "track2_inception_fold5.keras",
]

# Map zip-internal prefix -> destination directory under PKG_ROOT
EXTRACT_MAP = [
    ("csv/",            PKG_ROOT),
    ("models/cnn/",     PKG_ROOT / "CNN 파일"),
    ("models/sensor/",  PKG_ROOT / "models"),
    ("images/",         PKG_ROOT / "resize_640 x 360"),
]


def _all_present() -> bool:
    return all(p.exists() for p in REQUIRED_FILES)


def _download(url: str, dest: Path) -> None:
    print(f"[fetch] downloading {url}")
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        chunk = 1024 * 256
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            f.write(buf)
            read += len(buf)
            if total:
                pct = read * 100 / total
                print(f"\r[fetch] {read/1024/1024:.1f} / {total/1024/1024:.1f} MB ({pct:.1f}%)",
                      end="", flush=True)
    print()


def _extract(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for name in names:
            if name.endswith("/"):
                continue
            for prefix, dest_root in EXTRACT_MAP:
                if name.startswith(prefix):
                    rel = name[len(prefix):]
                    out = dest_root / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break


def main() -> int:
    if str(os.getenv("HACCP_SKIP_FETCH", "")).strip().lower() in {"1", "true", "yes"}:
        print("[fetch] HACCP_SKIP_FETCH set, skipping.")
        return 0

    if _all_present():
        print("[fetch] all runtime files present, skipping download.")
        return 0

    url = os.getenv("HACCP_RELEASE_URL", DEFAULT_RELEASE_URL).strip() or DEFAULT_RELEASE_URL

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / "release.zip"
        try:
            _download(url, zip_path)
        except Exception as exc:
            print(f"[fetch][ERROR] download failed: {exc}", file=sys.stderr)
            return 1
        try:
            _extract(zip_path)
        except Exception as exc:
            print(f"[fetch][ERROR] extract failed: {exc}", file=sys.stderr)
            return 1

    missing = [p for p in REQUIRED_FILES if not p.exists()]
    if missing:
        print("[fetch][WARN] some required files still missing:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        return 1

    print("[fetch] done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
