"""Dataset-local image split assignment and deterministic allocation."""

import hashlib
from collections import defaultdict
from typing import Any

SPLITS = ("train", "val", "test")
SPLIT_LABELS = {"train": "训练集", "val": "验证集", "test": "测试集", "unassigned": "未划分"}


def split_of(membership: dict[str, Any]) -> str:
    value = membership.get("split")
    return value if isinstance(value, str) and value != "unassigned" else "unassigned"


def allocation_preview(
    dataset_id: str,
    images: list[dict[str, Any]],
    ratios: dict[str, int],
) -> dict[str, Any]:
    """Assign only unassigned images, keeping identical content together."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in images:
        sha = item.get("sha256")
        key = ("hash", sha.lower(), int(item.get("size") or 0)) if sha else ("id", item["id"])
        groups[key].append(item)
    assignments: dict[str, str] = {}
    skipped: list[dict[str, Any]] = []
    categories = tuple(ratios)
    counts = {split: 0 for split in categories}
    total = sum(split_of(item) == "unassigned" for item in images)
    ratio_sum = sum(ratios.values())
    targets = {split: total * ratios[split] / ratio_sum for split in categories}
    ordered = sorted(groups.values(), key=lambda group: hashlib.sha256(
        (dataset_id + ":" + ",".join(sorted(item["id"] for item in group))).encode()
    ).hexdigest())
    for group in ordered:
        pending = [item for item in group if split_of(item) == "unassigned"]
        if not pending:
            continue
        existing = {split_of(item) for item in group if split_of(item) != "unassigned"}
        if len(existing) > 1:
            skipped.append({"asset_ids": sorted(item["id"] for item in pending), "assets": [{"id": item["id"], "name": item.get("name") or item["id"], "split": split_of(item)} for item in sorted(group, key=lambda item: item["id"])], "reason": "existing_split_conflict"})
            continue
        if existing:
            choice = next(iter(existing))
        else:
            choice = max(
                (split for split in categories if ratios[split] > 0),
                key=lambda split: (targets[split] - counts[split], -categories.index(split)),
            )
        for item in pending:
            assignments[item["id"]] = choice
        counts[choice] += len(pending)
    return {"assignments": assignments, "counts": counts, "skipped": skipped,
            "unassigned_count": total, "allocated_count": len(assignments)}
