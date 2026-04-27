"""
feature_extraction.py
=====================
이미지에서 feature를 추출하여 CSV로 저장하는 스크립트.

[추출 순서]
  Step 1 : 기초 통계량 11개
           mean_intensity, std_intensity, median_intensity,
           kurtosis, skewness, FWHMx, FWHMy,
           glcm_contrast, glcm_correlation, glcm_energy, glcm_homogeneity

  Step 2 : Sobel / HOG / Blob 관련 22개
           blob_count, blob_mean_area, blob_mean_circularity,
           blob_mean_eccentricity, blob_mean_orientation,
           canny_edges, lbp_hist_mean, lbp_hist_std,
           num_connected_components, largest_component_ratio,
           lbp_bin_00 ~ lbp_bin_09,
           fft_mean, fft_std, fft_max, fft_energy,
           sobel_mean, sobel_std, sobel_max, sobel_energy,
           hog_mean, hog_std, hog_max, hog_energy

  Step 3 : GLCM 4개 + Blob 4개  ← Step 1/2에 통합되어 있음
           (glcm_contrast, glcm_correlation, glcm_energy, glcm_homogeneity)
           (blob_count, blob_mean_area, blob_mean_circularity,
            blob_mean_eccentricity — blob_mean_orientation은 Step 2에 포함)

  Step 4 : 스펙클 grain 방향성 2개 ← Step 1에 통합되어 있음
           FWHMx (x방향 grain 크기), FWHMy (y방향 grain 크기)

  Step 5 : 메타데이터 4개
           label, file_name, sample_id, target

[사용법]
  python feature_extraction.py \
      --data_dir ./data_nested \
      --output   feature_V9_id.csv

  (CNN intermediate feature 추출: MobileNetV2 pooled 1280-dim)
  python feature_extraction.py \
      --mode cnn_intermediate \
      --data_dir "./resize_640 x 360" \
      --output mobilenetv2_intermediate_features.csv

  data_dir 하위 폴더 구조 예시:
      data_nested/
          glucose_mixed/
              ADULTERATED_CAMP10_SAD4_CUV1_*.png
          pure_milk/
              ...
"""

# ============================================================
# 0. Import
# ============================================================
import os
import glob
import argparse
import csv
import json
import sys
from pathlib import Path
from functools import lru_cache

import numpy as np

from scipy import stats

# Optional deps (handcrafted feature mode only)
try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None

try:
    from skimage.feature import canny, graycomatrix, graycoprops, hog, local_binary_pattern  # type: ignore
    from skimage.filters import sobel  # type: ignore
    from skimage.measure import label as sk_label, regionprops  # type: ignore
except Exception:  # pragma: no cover
    canny = None
    local_binary_pattern = None
    hog = None
    sk_label = None
    regionprops = None
    sobel = None
    graycomatrix = None
    graycoprops = None

try:
    from tqdm.auto import tqdm  # type: ignore
except Exception:  # pragma: no cover
    def tqdm(iterable, **_kwargs):
        return iterable


# ============================================================
# 1. 전처리 도우미 함수
# ============================================================

def preprocess_image(img_bgr: np.ndarray):
    """
    BGR 이미지를 받아 grayscale 정규화(0~1) 배열을 반환.
    Returns
    -------
    processed : np.ndarray (float64, 0~1)
    gray_uint8 : np.ndarray (uint8, 0~255)
    """
    if cv2 is None:
        raise ImportError("opencv-python is required for handcrafted feature extraction.")
    if len(img_bgr.shape) == 3 and img_bgr.shape[2] == 3:
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    elif len(img_bgr.shape) == 2:
        gray = img_bgr
    else:
        raise ValueError(f"지원하지 않는 이미지 shape: {img_bgr.shape}")

    gray_uint8 = gray.astype(np.uint8)
    processed  = gray_uint8 / 255.0
    return processed, gray_uint8


def compute_fwhm_axis(arr2d: np.ndarray):
    """
    2D 배열에서 x축/y축 방향의 FWHM을 계산.
    - FWHMx : 각 행의 intensity 합 프로파일 → 행 방향 폭
    - FWHMy : 각 열의 intensity 합 프로파일 → 열 방향 폭

    Returns
    -------
    fwhm_x, fwhm_y : float
    """
    def _fwhm_1d(profile):
        profile = profile.astype(float)
        max_val  = profile.max()
        if max_val == 0:
            return 0.0
        half_max = max_val / 2.0
        indices  = np.where(profile > half_max)[0]
        if len(indices) < 2:
            return 0.0
        return float(indices[-1] - indices[0])

    row_profile = arr2d.sum(axis=1)   # 행 방향 합산 → x 폭
    col_profile = arr2d.sum(axis=0)   # 열 방향 합산 → y 폭

    return _fwhm_1d(row_profile), _fwhm_1d(col_profile)


# ============================================================
# Step 1 : 기초 통계량 11개
# ============================================================

def extract_step1_basic_stats(processed: np.ndarray, gray_uint8: np.ndarray) -> dict:
    """
    mean_intensity, std_intensity, median_intensity,
    kurtosis, skewness, FWHMx, FWHMy,
    glcm_contrast, glcm_correlation, glcm_energy, glcm_homogeneity
    """
    feat = {}

    # ── 기초 통계 ───────────────────────────────────────────
    flat = processed.flatten()
    feat['mean_intensity']   = float(np.mean(processed))
    feat['std_intensity']    = float(np.std(processed))
    feat['median_intensity'] = float(np.median(processed))
    feat['kurtosis']         = float(stats.kurtosis(flat))
    feat['skewness']         = float(stats.skew(flat))

    # ── Step 4 : FWHMx / FWHMy (grain 방향성) ───────────────
    fwhm_x, fwhm_y = compute_fwhm_axis(processed)
    feat['FWHMx'] = fwhm_x
    feat['FWHMy'] = fwhm_y

    # ── Step 3 : GLCM 4개 ───────────────────────────────────
    # distances=[1], angles=[0] → 수평 방향 1픽셀 거리
    glcm = graycomatrix(
        gray_uint8,
        distances=[1],
        angles=[0],
        levels=256,
        symmetric=True,
        normed=True
    )
    feat['glcm_contrast']    = float(graycoprops(glcm, 'contrast')[0, 0])
    feat['glcm_correlation'] = float(graycoprops(glcm, 'correlation')[0, 0])
    feat['glcm_energy']      = float(graycoprops(glcm, 'energy')[0, 0])
    feat['glcm_homogeneity'] = float(graycoprops(glcm, 'homogeneity')[0, 0])

    return feat


# ============================================================
# Step 2 : Sobel / HOG / Blob 관련 22개
# ============================================================

def extract_step2_advanced(processed: np.ndarray, gray_uint8: np.ndarray) -> dict:
    """
    blob_count, blob_mean_area, blob_mean_circularity,
    blob_mean_eccentricity, blob_mean_orientation,
    canny_edges, lbp_hist_mean, lbp_hist_std,
    num_connected_components, largest_component_ratio,
    lbp_bin_00 ~ lbp_bin_09,
    fft_mean, fft_std, fft_max, fft_energy,
    sobel_mean, sobel_std, sobel_max, sobel_energy,
    hog_mean, hog_std, hog_max, hog_energy
    """
    feat = {}
    h, w = processed.shape

    # ── Step 3 : Blob 4개 (+ orientation) ───────────────────
    # blob = 밝은 영역 덩어리 (mean 이상인 픽셀 기준)
    binary     = processed > feat.get('mean_intensity', np.mean(processed))
    labeled    = sk_label(binary)
    props      = regionprops(labeled)

    feat['blob_count'] = len(props)
    if len(props) > 0:
        areas         = [p.area for p in props]
        circularities = [4 * np.pi * p.area / (p.perimeter ** 2)
                         if p.perimeter > 0 else 0.0 for p in props]
        feat['blob_mean_area']         = float(np.mean(areas))
        feat['blob_mean_circularity']  = float(np.mean(circularities))
        feat['blob_mean_eccentricity'] = float(np.mean([p.eccentricity for p in props]))
        feat['blob_mean_orientation']  = float(np.mean([p.orientation for p in props]))
    else:
        feat['blob_mean_area']         = 0.0
        feat['blob_mean_circularity']  = 0.0
        feat['blob_mean_eccentricity'] = 0.0
        feat['blob_mean_orientation']  = 0.0

    # ── Canny edge density ───────────────────────────────────
    edges = canny(processed, sigma=1.0)
    feat['canny_edges'] = float(np.sum(edges) / (h * w))

    # ── LBP histogram mean / std ─────────────────────────────
    lbp_img = local_binary_pattern(gray_uint8, P=8, R=1, method="uniform")
    hist, _  = np.histogram(lbp_img.ravel(), bins=np.arange(0, 10), range=(0, 9))
    hist     = hist.astype("float") / (hist.sum() + 1e-7)
    feat['lbp_hist_mean'] = float(np.mean(hist))
    feat['lbp_hist_std']  = float(np.std(hist))

    # ── Connected components ─────────────────────────────────
    cc_labeled = sk_label(binary)
    cc_props   = regionprops(cc_labeled)
    feat['num_connected_components'] = len(cc_props)
    if len(cc_props) > 0:
        largest_area = max(p.area for p in cc_props)
        feat['largest_component_ratio'] = float(largest_area / (h * w))
    else:
        feat['largest_component_ratio'] = 0.0

    # ── LBP bin 10개 ─────────────────────────────────────────
    lbp_bins_img = local_binary_pattern(gray_uint8, P=8, R=1, method="uniform")
    bin_hist, _  = np.histogram(lbp_bins_img.ravel(), bins=np.arange(0, 11), range=(0, 10))
    bin_hist     = bin_hist.astype("float") / (bin_hist.sum() + 1e-7)
    for i in range(10):
        feat[f'lbp_bin_{i:02d}'] = float(bin_hist[i])

    # ── FFT 4개 ──────────────────────────────────────────────
    magnitude = np.abs(np.fft.fftshift(np.fft.fft2(gray_uint8)))
    feat['fft_mean']   = float(np.mean(magnitude))
    feat['fft_std']    = float(np.std(magnitude))
    feat['fft_max']    = float(np.max(magnitude))
    feat['fft_energy'] = float(np.sum(magnitude ** 2))

    # ── Sobel 4개 ────────────────────────────────────────────
    sob = sobel(processed)
    feat['sobel_mean']   = float(np.mean(sob))
    feat['sobel_std']    = float(np.std(sob))
    feat['sobel_max']    = float(np.max(sob))
    feat['sobel_energy'] = float(np.sum(sob ** 2))

    # ── HOG 4개 ──────────────────────────────────────────────
    hog_desc = hog(
        gray_uint8,
        orientations=8,
        pixels_per_cell=(16, 16),
        cells_per_block=(1, 1),
        feature_vector=True
    )
    feat['hog_mean']   = float(np.mean(hog_desc))
    feat['hog_std']    = float(np.std(hog_desc))
    feat['hog_max']    = float(np.max(hog_desc))
    feat['hog_energy'] = float(np.sum(hog_desc ** 2))

    return feat


# ============================================================
# 전체 feature 추출 통합 함수
# ============================================================

def extract_features_from_image(img_bgr: np.ndarray) -> dict:
    """
    BGR 이미지 배열 → feature dict 반환.
    Step 1 (11개) + Step 2 (22개) = 총 43개 feature
    """
    if cv2 is None or canny is None or hog is None or sk_label is None:
        raise ImportError(
            "Handcrafted feature extraction requires optional dependencies. "
            "Install `opencv-python` and `scikit-image` (and optionally `tqdm`)."
        )

    processed, gray_uint8 = preprocess_image(img_bgr)

    feat = {}
    feat.update(extract_step1_basic_stats(processed, gray_uint8))
    feat.update(extract_step2_advanced(processed, gray_uint8))

    return feat


# ============================================================
# Step 5 : 메타데이터 파싱 유틸
# ============================================================

def parse_metadata(file_path: str) -> dict:
    """
    file_path 예시 (두 가지 패턴 모두 지원):
      [패턴 A] ./data_nested/glucose_mixed/ADULTERATED_CAMP10_SAD4_CUV1_JUG5_frame_0.png
      [패턴 B] ./resize_1280x720/water_mixed/JUG1_CAMP1_SAD2_CUV1_frame_0.png

    Returns
    -------
    dict with keys: file_name, sample_id, label, target
      - sample_id : 바로 위 폴더명 (e.g. glucose_mixed, water_mixed)
      - label / target 결정 우선순위:
          1순위 : 파일명에 'UNADULTERATED' → 'unadulterated'
                  파일명에 'ADULTERATED'   → 'adulterated'   (UNADULTERATED 먼저 체크)
          2순위 : 파일명에 'CUV2' → 'unadulterated'
                  파일명에 'CUV1' → 'adulterated'
          3순위 : 위 패턴 모두 없으면 → 'unknown'
    """
    p         = Path(file_path)
    sample_id = p.parent.name
    fname     = p.name.upper()

    # 1순위: 파일명에 명시적 ADULTERATED 접두사가 있는 경우 (패턴 A)
    if 'UNADULTERATED' in fname:
        label = 'unadulterated'
    elif 'ADULTERATED' in fname:
        label = 'adulterated'
    # 2순위: CUV 번호로 구분하는 경우 (패턴 B)
    #   CUV1 = adulterated (오염됨)
    #   CUV2 = unadulterated (순수)
    elif 'CUV2' in fname:
        label = 'unadulterated'
    elif 'CUV1' in fname:
        label = 'adulterated'
    # 3순위: 판단 불가
    else:
        label = 'unknown'

    return {
        'file_name' : str(file_path),
        'sample_id' : sample_id,
        'label'     : label,
        'target'    : label,
    }


# ============================================================
# CNN 기반 feature 추출 (MobileNetV2 intermediate features)
# ============================================================

_CNN_ASSET_DIR = (Path(__file__).resolve().parent / "CNN 파일").resolve()
_CNN_MODEL_PATH = _CNN_ASSET_DIR / "mobilenetv2_final_full.pt"
_CNN_LABELS_PATH = _CNN_ASSET_DIR / "labels.json"
_CNN_PREPROCESS_CONFIG_PATH = _CNN_ASSET_DIR / "preprocess_config.json"


def _resolve_device(device: str):
    import torch

    raw = (device or os.getenv("HACCP_IMAGE_DEVICE", "cpu") or "cpu").strip().lower()
    if raw in {"cuda", "gpu"}:
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if raw.startswith("cuda:"):
        try:
            return torch.device(raw)
        except Exception:
            return torch.device("cpu")
    return torch.device("cpu")


def _load_labels():
    if not _CNN_LABELS_PATH.exists():
        raise FileNotFoundError(f"labels.json not found: {_CNN_LABELS_PATH}")
    raw = json.loads(_CNN_LABELS_PATH.read_text(encoding="utf-8"))
    labels = {int(k): str(v) for k, v in raw.items()}
    if not labels:
        raise ValueError("labels.json is empty.")
    label_to_index = {v: k for k, v in labels.items()}
    return labels, label_to_index


def _load_preprocess_config():
    if not _CNN_PREPROCESS_CONFIG_PATH.exists():
        return {
            "input_size": 448,
            "crop_size": 448,
            "grayscale": True,
            "normalize_mean": [0.5],
            "normalize_std": [0.5],
        }
    return json.loads(_CNN_PREPROCESS_CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=2)
def _load_cnn_model(device: str = "cpu"):
    """
    NOTE: `mobilenetv2_final_full.pt` in this repo is a pickled `torchvision` model.
    Loading pickled torch models can execute code. Only run this with a trusted file.
    """
    import torch

    if not _CNN_MODEL_PATH.exists():
        raise FileNotFoundError(f"CNN model file not found: {_CNN_MODEL_PATH}")

    dev = _resolve_device(device)
    with _CNN_MODEL_PATH.open("rb") as handle:
        try:
            model = torch.jit.load(handle, map_location="cpu")
        except Exception:
            handle.seek(0)
            try:
                model = torch.load(handle, map_location="cpu", weights_only=False)
            except TypeError:
                handle.seek(0)
                model = torch.load(handle, map_location="cpu")

    model.eval()
    model.to(dev)
    return model, dev


@lru_cache(maxsize=1)
def _build_cnn_transform():
    config = _load_preprocess_config()
    input_size = int(config.get("input_size", 448))
    crop_size = int(config.get("crop_size", input_size))
    grayscale = bool(config.get("grayscale", True))
    mean = config.get("normalize_mean", [0.5] if grayscale else [0.5, 0.5, 0.5])
    std = config.get("normalize_std", [0.5] if grayscale else [0.5, 0.5, 0.5])

    from torchvision import transforms as T

    steps = [
        T.Resize(input_size),
        T.CenterCrop(crop_size),
    ]
    if grayscale:
        steps.append(T.Grayscale(num_output_channels=1))
    steps.extend(
        [
            T.ToTensor(),
            T.Normalize(mean=mean, std=std),
        ]
    )
    return T.Compose(steps)


def _infer_true_label_from_folder(file_path: str, label_to_index: dict[str, int]) -> int:
    folder = Path(file_path).parent.name
    return int(label_to_index.get(folder, -1))


def extract_cnn_intermediate_features(image_path: str, device: str = "cpu", dtype: str = "float16"):
    import torch
    from PIL import Image

    model, dev = _load_cnn_model(device=device)
    transform = _build_cnn_transform()

    img = Image.open(image_path).convert("RGB")
    tensor = transform(img).unsqueeze(0).to(dev)

    with torch.inference_mode():
        feat_map = model.features(tensor)
        pooled = torch.nn.functional.adaptive_avg_pool2d(feat_map, (1, 1)).flatten(1)  # (1, 1280)
        logits = model.classifier(pooled)
        probs = torch.nn.functional.softmax(logits, dim=-1).flatten(0)

    if str(dtype).lower() == "float16":
        pooled = pooled.to(torch.float16)
        probs = probs.to(torch.float16)
    else:
        pooled = pooled.to(torch.float32)
        probs = probs.to(torch.float32)

    feat_vector = pooled.flatten(0).detach().to("cpu").numpy()
    prob_vector = probs.detach().to("cpu").numpy()
    pred_class = int(prob_vector.argmax())

    return feat_vector, prob_vector, pred_class


def run_cnn_feature_extraction(
    data_dir: str,
    output_csv: str,
    device: str = "cpu",
    output_type: str = "intermediate",
    dtype: str = "float16",
):
    labels, label_to_index = _load_labels()
    image_paths = collect_image_paths(data_dir)
    if not image_paths:
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {data_dir}")

    output_type = (output_type or "intermediate").strip().lower()
    if output_type not in {"intermediate", "fusion_ready"}:
        raise ValueError("output_type must be one of: intermediate, fusion_ready")

    if output_type == "intermediate":
        header = ["filename", "true_label"] + [f"feat_{i:04d}" for i in range(1280)]
    else:
        header = ["filename", "true_label", "true_class", "prob_class_0", "prob_class_1", "prob_class_2", "pred_class"]

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)

        for path in tqdm(image_paths, desc=f"CNN feature extraction ({output_type})"):
            try:
                feat_vector, prob_vector, pred_class = extract_cnn_intermediate_features(path, device=device, dtype=dtype)
            except Exception as exc:
                print(f"[WARN] CNN extract failed, skip: {path} ({exc})", file=sys.stderr)
                continue

            filename = Path(path).name
            true_label = _infer_true_label_from_folder(path, label_to_index)
            if output_type == "intermediate":
                row = [filename, true_label] + [float(x) for x in feat_vector.tolist()]
            else:
                true_class = labels.get(true_label, "unknown") if true_label >= 0 else "unknown"
                row = [
                    filename,
                    true_label,
                    true_class,
                    float(prob_vector[0]),
                    float(prob_vector[1]),
                    float(prob_vector[2]),
                    pred_class,
                ]
            writer.writerow(row)

    print(f"\n완료! 결과 저장: {output_csv}")


# ============================================================
# 메인 파이프라인
# ============================================================

def collect_image_paths(data_dir: str) -> list:
    """data_dir 하위의 모든 .png / .jpg / .jpeg 경로를 재귀 수집."""
    patterns = ['**/*.png', '**/*.jpg', '**/*.jpeg']
    paths = []
    for pat in patterns:
        paths.extend(glob.glob(os.path.join(data_dir, pat), recursive=True))
    return sorted(paths)


def run_extraction(data_dir: str, output_csv: str):
    if cv2 is None or canny is None or hog is None or sk_label is None:
        raise ImportError(
            "This script is running in handcrafted mode, but optional dependencies are missing. "
            "Install `opencv-python` and `scikit-image`."
        )

    image_paths = collect_image_paths(data_dir)
    if not image_paths:
        raise FileNotFoundError(f"이미지 파일을 찾을 수 없습니다: {data_dir}")

    print(f"총 {len(image_paths)}개 이미지 발견 → feature 추출 시작")

    # ── 컬럼 순서를 최종 CSV와 동일하게 정렬 ──────────────────
    COL_ORDER = [
        'mean_intensity', 'std_intensity', 'median_intensity',
        'kurtosis', 'skewness', 'FWHMx', 'FWHMy',
        'glcm_contrast', 'glcm_correlation', 'glcm_energy', 'glcm_homogeneity',
        'blob_count', 'blob_mean_area', 'blob_mean_circularity',
        'blob_mean_eccentricity', 'blob_mean_orientation',
        'canny_edges', 'lbp_hist_mean', 'lbp_hist_std',
        'num_connected_components', 'largest_component_ratio',
        'lbp_bin_00', 'lbp_bin_01', 'lbp_bin_02', 'lbp_bin_03', 'lbp_bin_04',
        'lbp_bin_05', 'lbp_bin_06', 'lbp_bin_07', 'lbp_bin_08', 'lbp_bin_09',
        'fft_mean', 'fft_std', 'fft_max', 'fft_energy',
        'sobel_mean', 'sobel_std', 'sobel_max', 'sobel_energy',
        'hog_mean', 'hog_std', 'hog_max', 'hog_energy',
        'label', 'file_name', 'sample_id', 'target',
    ]

    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(output_csv, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COL_ORDER)

        for path in tqdm(image_paths, desc="Extracting handcrafted features"):
            img = cv2.imread(path)
            if img is None:
                print(f"  [WARN] 읽기 실패, 건너뜀: {path}")
                continue

            feat = extract_features_from_image(img)
            feat.update(parse_metadata(path))

            writer.writerow([feat.get(column, 0.0) for column in COL_ORDER])
            written += 1

    print(f"\n완료! {written}개 행 → {output_csv}")
    print(f"컬럼 수: {len(COL_ORDER)}개")


# ============================================================
# CLI 진입점
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='이미지 feature 추출 → CSV 저장 (handcrafted / CNN intermediate)'
    )
    parser.add_argument(
        '--mode',
        type=str,
        default='cnn_intermediate',
        choices=['cnn_intermediate', 'cnn_fusion_ready', 'handcrafted'],
        help='추출 방식 선택 (기본값: cnn_intermediate)',
    )
    parser.add_argument(
        '--data_dir',
        type=str,
        default='./resize_640 x 360',
        help='이미지가 들어있는 루트 디렉토리 (재귀 탐색)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='cnn_intermediate_features.csv',
        help='출력 CSV 파일명'
    )
    parser.add_argument(
        '--device',
        type=str,
        default=os.getenv("HACCP_IMAGE_DEVICE", "cpu"),
        help='Torch device (cpu/cuda/cuda:0). 기본은 HACCP_IMAGE_DEVICE 또는 cpu',
    )
    parser.add_argument(
        '--dtype',
        type=str,
        default='float16',
        choices=['float16', 'float32'],
        help='CNN feature/prob 저장 dtype (기본값: float16)',
    )
    args = parser.parse_args()

    if args.mode == 'handcrafted':
        run_extraction(args.data_dir, args.output)
    elif args.mode == 'cnn_fusion_ready':
        run_cnn_feature_extraction(args.data_dir, args.output, device=args.device, output_type='fusion_ready', dtype=args.dtype)
    else:
        run_cnn_feature_extraction(args.data_dir, args.output, device=args.device, output_type='intermediate', dtype=args.dtype)
