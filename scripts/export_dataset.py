"""Export a minimized dataset package for GitHub Release distribution.

Image sampling ratio (fixed):
    pure_milk     : 0.7
    water_mixed   : 0.2
    glucose_mixed : 0.1

Usage:
    python scripts/export_dataset.py --total 1000
    python scripts/export_dataset.py --total 500 --clean
    python scripts/export_dataset.py --total 1000 --out dataset_export

Output structure (under --out):
    csv/
        batch_150_contaminated_onlylabel_final_v4.csv
        sample_inference_input_19f.csv
    models/
        cnn/
            mobilenetv2_final_full.pt
            labels.json
            preprocess_config.json
            best_weight_w.json
        sensor/
            track1_inception_fold5.keras
            track2_inception_fold5.keras
    images/
        pure_milk/      (700 imgs by default)
        water_mixed/    (200 imgs)
        glucose_mixed/  (100 imgs)
    README.md
"""
from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

# ---- Configuration -----------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
PKG_ROOT = REPO_ROOT / "haccp_dashboard"

RATIOS = {
    "pure_milk": 0.7,
    "water_mixed": 0.2,
    "glucose_mixed": 0.1,
}

IMAGE_ROOT = PKG_ROOT / "resize_640 x 360"

# (source, relative dest under output dir)
RUNTIME_FILES: list[tuple[Path, str]] = [
    # CSVs
    (PKG_ROOT / "batch_150_contaminated_onlylabel_final_v4.csv",
     "csv/batch_150_contaminated_onlylabel_final_v4.csv"),
    (PKG_ROOT / "sample_inference_input_19f.csv",
     "csv/sample_inference_input_19f.csv"),
    # CNN model + configs
    (PKG_ROOT / "CNN 파일" / "mobilenetv2_final_full.pt",
     "models/cnn/mobilenetv2_final_full.pt"),
    (PKG_ROOT / "CNN 파일" / "labels.json",
     "models/cnn/labels.json"),
    (PKG_ROOT / "CNN 파일" / "preprocess_config.json",
     "models/cnn/preprocess_config.json"),
    (PKG_ROOT / "CNN 파일" / "best_weight_w.json",
     "models/cnn/best_weight_w.json"),
    # Sensor models
    (PKG_ROOT / "models" / "track1_inception_fold5.keras",
     "models/sensor/track1_inception_fold5.keras"),
    (PKG_ROOT / "models" / "track2_inception_fold5.keras",
     "models/sensor/track2_inception_fold5.keras"),
]

README_TEMPLATE = """# HACCP Dashboard - Dataset & Model Package

This archive contains the minimum runtime data required to reproduce the
dashboard inference pipeline.

## Image sampling ratio

| Class         | Ratio | Count (total={total}) |
|---------------|-------|------------------------|
| pure_milk     | 0.70  | {n_pure}               |
| water_mixed   | 0.20  | {n_water}              |
| glucose_mixed | 0.10  | {n_glucose}            |

## Layout

```
csv/                                CSV inputs used by the dashboard
models/cnn/                         MobileNetV2 image model + configs
models/sensor/                      Inception sensor models (track1/2)
images/<class>/                     Sampled PNG frames
```

## How to use

1. Download and unzip into the repo root.
2. Place `csv/*.csv` files into `haccp_dashboard/`.
3. Place `models/cnn/*` into `haccp_dashboard/CNN 파일/`.
4. Place `models/sensor/*.keras` into `haccp_dashboard/models/`.
5. Place `images/<class>/` into `haccp_dashboard/resize_640 x 360/<class>/`.

Source code: https://github.com/juhan9437-dotcom/haccp_dashboard
"""


# ---- Helpers -----------------------------------------------------------------

def _copy_runtime_files(out_dir: Path) -> list[str]:
    missing: list[str] = []
    for src, rel_dest in RUNTIME_FILES:
        dest = out_dir / rel_dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not src.exists():
            missing.append(str(src))
            continue
        shutil.copy2(src, dest)
        print(f"  [+] {rel_dest}  ({src.stat().st_size/1024/1024:.2f} MB)")
    return missing


def _sample_images(out_dir: Path, total: int, seed: int) -> dict[str, int]:
    rng = random.Random(seed)
    counts: dict[str, int] = {}
    image_root_dst = out_dir / "images"
    image_root_dst.mkdir(parents=True, exist_ok=True)

    for cls, ratio in RATIOS.items():
        src_dir = IMAGE_ROOT / cls
        dst_dir = image_root_dst / cls
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not src_dir.exists():
            print(f"  [!] missing image folder: {src_dir}")
            counts[cls] = 0
            continue
        all_imgs = sorted(
            p for p in src_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".png", ".jpg", ".jpeg")
        )
        target_n = int(round(total * ratio))
        target_n = min(target_n, len(all_imgs))
        picked = rng.sample(all_imgs, target_n) if target_n > 0 else []
        for p in picked:
            shutil.copy2(p, dst_dir / p.name)
        counts[cls] = len(picked)
        print(f"  [+] images/{cls}: {len(picked)} / {len(all_imgs)} sampled")
    return counts


def _write_readme(out_dir: Path, total: int, counts: dict[str, int]) -> None:
    readme = README_TEMPLATE.format(
        total=total,
        n_pure=counts.get("pure_milk", 0),
        n_water=counts.get("water_mixed", 0),
        n_glucose=counts.get("glucose_mixed", 0),
    )
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


# ---- Entry -------------------------------------------------------------------

def export(total: int, out_dir: Path, seed: int, clean: bool) -> int:
    if clean and out_dir.exists():
        print(f"[clean] removing {out_dir}")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/3] copy runtime files -> {out_dir}")
    missing = _copy_runtime_files(out_dir)

    print(f"[2/3] sample images (total={total}, seed={seed})")
    counts = _sample_images(out_dir, total=total, seed=seed)

    print("[3/3] write README.md")
    _write_readme(out_dir, total=total, counts=counts)

    if missing:
        print("\n[WARN] missing source files (skipped):")
        for m in missing:
            print(f"  - {m}")

    print(f"\nDone. Output dir: {out_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Export minimal HACCP dataset for release")
    parser.add_argument("--total", type=int, default=1000,
                        help="Total number of images to sample (default: 1000)")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "dataset_export",
                        help="Output directory (default: ./dataset_export)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--clean", action="store_true", help="Remove output dir first")
    args = parser.parse_args()
    return export(total=args.total, out_dir=args.out, seed=args.seed, clean=args.clean)


if __name__ == "__main__":
    sys.exit(main())
