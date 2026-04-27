from __future__ import annotations

import io
import json
import os
from pathlib import Path


def _resolve_asset_dir() -> Path:
    override = (os.getenv("HACCP_IMAGE_ASSET_DIR", "") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "CNN 파일").resolve()


ASSET_DIR = _resolve_asset_dir()
# Note: `mobilenetv2_final_full.pt` in this repo is a pickled `torchvision` model
# (loaded via `torch.load(weights_only=False)`), not a TorchScript archive.
MODEL_FULL_PATH = ASSET_DIR / "mobilenetv2_final_full.pt"
MODEL_STATE_DICT_PATH = ASSET_DIR / "mobilenetv2_final.pth"
LABELS_PATH = ASSET_DIR / "labels.json"
PREPROCESS_CONFIG_PATH = ASSET_DIR / "preprocess_config.json"

_TORCH = None
_MODEL = None
_TRANSFORM = None
_LABELS = None
_LOAD_ERROR = None
_LOAD_ATTEMPTED = False


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_device(torch_module):
    raw = (os.getenv("HACCP_IMAGE_DEVICE", "cpu") or "cpu").strip().lower()
    if raw in {"cuda", "gpu"}:
        return torch_module.device("cuda" if torch_module.cuda.is_available() else "cpu")
    if raw.startswith("cuda:"):
        try:
            return torch_module.device(raw)
        except Exception:
            return torch_module.device("cpu")
    return torch_module.device("cpu")


def _build_transform(torchvision_transforms):
    config = _load_json(PREPROCESS_CONFIG_PATH) if PREPROCESS_CONFIG_PATH.exists() else {}
    input_size = int(config.get("input_size", 448))
    crop_size = int(config.get("crop_size", input_size))
    grayscale = bool(config.get("grayscale", True))
    mean = config.get("normalize_mean", [0.5] if grayscale else [0.5, 0.5, 0.5])
    std = config.get("normalize_std", [0.5] if grayscale else [0.5, 0.5, 0.5])

    steps = [
        torchvision_transforms.Resize(input_size),
        torchvision_transforms.CenterCrop(crop_size),
    ]
    if grayscale:
        steps.append(torchvision_transforms.Grayscale(num_output_channels=1))
    steps.extend(
        [
            torchvision_transforms.ToTensor(),
            torchvision_transforms.Normalize(mean=mean, std=std),
        ]
    )
    return torchvision_transforms.Compose(steps), {
        "input_size": input_size,
        "crop_size": crop_size,
        "grayscale": grayscale,
        "normalize_mean": mean,
        "normalize_std": std,
    }


def _load_assets_once():
    global _TORCH, _MODEL, _TRANSFORM, _LABELS, _LOAD_ERROR, _LOAD_ATTEMPTED

    if _MODEL is not None and _TRANSFORM is not None and _LABELS is not None:
        return
    if _LOAD_ERROR is not None:
        return

    _LOAD_ATTEMPTED = True

    try:
        import torch
        from PIL import Image
        from torchvision import transforms as T

        missing = [
            str(path)
            for path in (LABELS_PATH, PREPROCESS_CONFIG_PATH)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"Missing CNN assets: {', '.join(missing)}")

        labels_raw = _load_json(LABELS_PATH)
        labels = {int(k): str(v) for k, v in labels_raw.items()}
        if not labels:
            raise ValueError("labels.json is empty.")

        transform, preprocess_config = _build_transform(T)
        device = _resolve_device(torch)

        model = None
        load_errors: list[str] = []

        if MODEL_FULL_PATH.exists():
            try:
                # Try TorchScript first (harmless if not a TS archive).
                with MODEL_FULL_PATH.open("rb") as handle:
                    model = torch.jit.load(handle, map_location="cpu")
            except Exception as exc:
                load_errors.append(f"torch.jit.load failed: {exc}")
                model = None

            if model is None:
                try:
                    # This repo's .pt is a pickled `torchvision` module.
                    with MODEL_FULL_PATH.open("rb") as handle:
                        model = torch.load(handle, map_location="cpu", weights_only=False)
                except TypeError:
                    # Older torch versions may not support `weights_only`.
                    with MODEL_FULL_PATH.open("rb") as handle:
                        model = torch.load(handle, map_location="cpu")
                except Exception as exc:
                    load_errors.append(f"torch.load failed: {exc}")
                    model = None

        if model is None:
            details = " | ".join(load_errors) if load_errors else "no load attempts"
            raise FileNotFoundError(f"Unable to load CNN model from {ASSET_DIR}. ({details})")

        model.eval()
        model.to(device)

        _TORCH = torch
        _MODEL = model
        _TRANSFORM = transform
        _LABELS = labels
        _LOAD_ERROR = None

        # Keep small runtime debug info in env var-friendly format.
        _ = preprocess_config
        _ = Image  # noqa: F841
    except Exception as exc:
        _LOAD_ERROR = str(exc)


def get_image_inference_status(attempt_load: bool = False) -> dict:
    if attempt_load:
        _load_assets_once()

    return {
        "ready": _MODEL is not None and _TRANSFORM is not None and _LABELS is not None,
        "error": _LOAD_ERROR,
        "load_attempted": _LOAD_ATTEMPTED,
        "asset_dir": str(ASSET_DIR),
        "assets_present": all(
            path.exists()
            for path in (
                LABELS_PATH,
                PREPROCESS_CONFIG_PATH,
                MODEL_FULL_PATH,
            )
        ),
    }


def _softmax(torch_module, logits):
    return torch_module.nn.functional.softmax(logits, dim=-1)


def predict_image_class(image_bytes: bytes, topk: int = 3) -> dict:
    _load_assets_once()
    if _LOAD_ERROR is not None:
        raise RuntimeError(_LOAD_ERROR)

    if not image_bytes:
        raise ValueError("Empty image payload.")

    from PIL import Image

    torch = _TORCH
    device = next(_MODEL.parameters()).device if hasattr(_MODEL, "parameters") else torch.device("cpu")

    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")

    tensor = _TRANSFORM(image).unsqueeze(0).to(device)

    with torch.inference_mode():
        outputs = _MODEL(tensor)
        logits = outputs if outputs.ndim == 2 else outputs.reshape(1, -1)
        probs = _softmax(torch, logits)[0].detach().to("cpu")

    k = max(1, min(int(topk), int(probs.shape[0])))
    top_probs, top_indices = torch.topk(probs, k)

    scored = []
    for prob, idx in zip(top_probs.tolist(), top_indices.tolist(), strict=False):
        scored.append(
            {
                "index": int(idx),
                "label": _LABELS.get(int(idx), str(idx)),
                "prob": float(prob),
            }
        )

    best = scored[0]
    return {
        "label": best["label"],
        "index": best["index"],
        "prob": best["prob"],
        "topk": scored,
        "class_count": int(len(_LABELS)),
        "asset_dir": str(ASSET_DIR),
        "model_file": str(MODEL_FULL_PATH if MODEL_FULL_PATH.exists() else MODEL_STATE_DICT_PATH),
    }
