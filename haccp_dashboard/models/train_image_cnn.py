from __future__ import annotations

import argparse
import json
from pathlib import Path


def _set_seed(seed: int):
    import random

    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def _load_or_build_model(num_classes: int, asset_dir: Path, use_existing: bool):
    import torch
    from torchvision import models

    model = None
    if use_existing:
        candidate = asset_dir / "mobilenetv2_final_full.pt"
        if candidate.exists():
            try:
                with candidate.open("rb") as handle:
                    model = torch.jit.load(handle, map_location="cpu")
            except Exception:
                model = None
            if model is None:
                try:
                    with candidate.open("rb") as handle:
                        model = torch.load(handle, map_location="cpu", weights_only=False)
                except TypeError:
                    with candidate.open("rb") as handle:
                        model = torch.load(handle, map_location="cpu")
                except Exception:
                    model = None

    if model is None:
        model = models.mobilenet_v2(weights=None)

    # Ensure classifier head matches the dataset classes.
    if hasattr(model, "classifier") and hasattr(model.classifier, "__len__"):
        last = model.classifier[-1]
        in_features = getattr(last, "in_features", None)
        if in_features is not None:
            import torch.nn as nn

            model.classifier[-1] = nn.Linear(int(in_features), int(num_classes))
    return model


def main():
    parser = argparse.ArgumentParser(description="Train image CNN (MobileNetV2) from resize_640 x 360 dataset.")
    parser.add_argument("--data-dir", default="", help="Image dataset dir (default: project common path).")
    parser.add_argument("--output-dir", default="", help="Asset output dir (default: haccp_dashboard/CNN 파일).")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--init-from-existing",
        action="store_true",
        help="Initialize from existing mobilenetv2_final_full.pt if present.",
    )
    args = parser.parse_args()

    from haccp_dashboard.lib.main_helpers import resolve_image_dataset_dir

    data_dir = Path(args.data_dir).expanduser() if str(args.data_dir).strip() else Path(resolve_image_dataset_dir())
    output_dir = Path(args.output_dir).expanduser() if str(args.output_dir).strip() else (Path(__file__).resolve().parents[1] / "CNN 파일")
    output_dir.mkdir(parents=True, exist_ok=True)

    import torch
    from torch import nn
    from torch.utils.data import DataLoader, random_split
    from torchvision import datasets, transforms

    _set_seed(int(args.seed))

    preprocess_config = {
        "input_size": 448,
        "crop_size": 448,
        "grayscale": True,
        "normalize_mean": [0.5],
        "normalize_std": [0.5],
    }
    transform = transforms.Compose(
        [
            transforms.Resize(preprocess_config["input_size"]),
            transforms.CenterCrop(preprocess_config["crop_size"]),
            transforms.Grayscale(num_output_channels=1),
            transforms.ToTensor(),
            transforms.Normalize(mean=preprocess_config["normalize_mean"], std=preprocess_config["normalize_std"]),
        ]
    )

    dataset = datasets.ImageFolder(str(data_dir), transform=transform)
    if len(dataset.classes) < 2:
        raise ValueError(f"Expected >=2 classes under {data_dir}, got: {dataset.classes}")

    val_size = max(1, int(len(dataset) * 0.2))
    train_size = max(1, len(dataset) - val_size)
    train_ds, val_ds = random_split(dataset, [train_size, val_size], generator=torch.Generator().manual_seed(int(args.seed)))

    train_loader = DataLoader(train_ds, batch_size=int(args.batch_size), shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=int(args.batch_size), shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = _load_or_build_model(len(dataset.classes), output_dir, bool(args.init_from_existing))
    model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(model.parameters(), lr=float(args.lr))

    best_val_acc = -1.0
    best_state = None

    for epoch in range(int(args.epochs)):
        model.train()
        running_loss = 0.0
        for images, labels in train_loader:
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item()) * int(images.shape[0])

        model.eval()
        correct = 0
        total = 0
        with torch.inference_mode():
            for images, labels in val_loader:
                images = images.to(device)
                labels = labels.to(device)
                logits = model(images)
                preds = logits.argmax(dim=1)
                correct += int((preds == labels).sum().item())
                total += int(labels.numel())

        val_acc = (correct / total) if total else 0.0
        train_loss = running_loss / max(1, train_size)
        print(f"epoch={epoch+1}/{args.epochs} train_loss={train_loss:.4f} val_acc={val_acc:.4f}")

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    labels_path = output_dir / "labels.json"
    preprocess_path = output_dir / "preprocess_config.json"
    model_full_path = output_dir / "mobilenetv2_final_full.pt"
    model_state_path = output_dir / "mobilenetv2_final.pth"

    labels_json = {int(i): name for i, name in enumerate(dataset.classes)}
    labels_path.write_text(json.dumps(labels_json, ensure_ascii=False, indent=2), encoding="utf-8")
    preprocess_path.write_text(json.dumps(preprocess_config, ensure_ascii=False, indent=2), encoding="utf-8")

    # Save both pickled full model and a state_dict for portability.
    torch.save(model.cpu(), model_full_path)
    torch.save(model.state_dict(), model_state_path)

    print(f"[OK] Saved labels: {labels_path}")
    print(f"[OK] Saved preprocess config: {preprocess_path}")
    print(f"[OK] Saved model (full): {model_full_path}")
    print(f"[OK] Saved model (state_dict): {model_state_path}")


if __name__ == "__main__":
    main()

