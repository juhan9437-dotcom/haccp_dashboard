from __future__ import annotations

from dataclasses import dataclass

RiskLevel = str  # "정상" | "경고" | "위험"

# 최종제품공정(출하판정) 배치 기준
# - 정상: 확정 부적합 0건 AND 의심 샘플 0건  → 출하 가능(적합)
# - 경고: 확정 부적합 0건 AND 의심 샘플 ≥ 1건 → 출하 보류(재검/추가확인)  ※ 내부 운영 기준
# - 위험: 확정 부적합 ≥ 1건 → 즉시 출하 보류/격리(부적합)
FINAL_WARNING_SUSPECT_MIN = 1


@dataclass(frozen=True)
class FinalProductBatchDecision:
    level: RiskLevel
    shipment_ok: bool
    confirmed_nonconforming_count: int
    suspect_count: int
    sample_count: int
    disposition: str  # "출하 가능" | "보류(재검)" | "출하 보류"


def classify_final_product_batch(
    *,
    confirmed_nonconforming_count: int,
    suspect_count: int,
    sample_count: int,
    warning_suspect_min: int = FINAL_WARNING_SUSPECT_MIN,
) -> FinalProductBatchDecision:
    confirmed = max(int(confirmed_nonconforming_count), 0)
    suspect = max(int(suspect_count), 0)
    total = max(int(sample_count), 0)

    if confirmed >= 1:
        return FinalProductBatchDecision(
            level="위험",
            shipment_ok=False,
            confirmed_nonconforming_count=confirmed,
            suspect_count=suspect,
            sample_count=total,
            disposition="출하 보류",
        )

    if suspect >= max(int(warning_suspect_min), 1):
        return FinalProductBatchDecision(
            level="경고",
            shipment_ok=False,
            confirmed_nonconforming_count=confirmed,
            suspect_count=suspect,
            sample_count=total,
            disposition="보류(재검)",
        )

    return FinalProductBatchDecision(
        level="정상",
        shipment_ok=True,
        confirmed_nonconforming_count=confirmed,
        suspect_count=suspect,
        sample_count=total,
        disposition="출하 가능",
    )

