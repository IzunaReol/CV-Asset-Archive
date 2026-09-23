"""Measure common asset queries against 100k synthetic documents in an isolated database."""

import argparse
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, MongoClient


def measure(operation, repetitions: int = 25) -> float:
    timings = []
    for _ in range(repetitions):
        started = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - started) * 1000)
    return sorted(timings)[int((len(timings) - 1) * 0.95)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="mongodb://localhost:27017")
    parser.add_argument("--count", type=int, default=100_000)
    args = parser.parse_args()
    if args.count < 1000 or args.count > 1_000_000:
        parser.error("--count 必须在 1000 到 1000000 之间")
    database_name = f"cv_archive_perf_{uuid4().hex[:12]}"
    client = MongoClient(args.uri, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    database = client[database_name]
    assets = database.assets
    try:
        assets.create_index([("archived_at", ASCENDING), ("created_at", DESCENDING)])
        assets.create_index([("archived_at", ASCENDING), ("type", ASCENDING),
                             ("created_at", DESCENDING), ("id", ASCENDING)])
        assets.create_index([("sha256", ASCENDING), ("size", ASCENDING)])
        base_time = datetime.now(UTC)
        for offset in range(0, args.count, 1000):
            batch = []
            for index in range(offset, min(offset + 1000, args.count)):
                asset_type = ("image", "video", "annotation", "archive")[index % 4]
                batch.append({
                    "id": f"perf-{index:08d}", "name": f"男人抽烟_{index}.jpg" if index % 100 == 0 else f"素材_{index}.jpg",
                    "type": asset_type, "remark": "室外夜间" if index % 20 == 0 else "",
                    "tags": {"status": ["已标注"]} if index % 3 == 0 else {},
                    "size": 1024 + index, "archived_at": None,
                    "created_at": base_time - timedelta(seconds=index),
                })
            assets.insert_many(batch, ordered=False)
        queries = {
            "最近素材": lambda: list(assets.find({"archived_at": None}).sort(
                [("created_at", DESCENDING), ("id", ASCENDING)]).limit(50)),
            "图片筛选": lambda: list(assets.find({"archived_at": None, "type": "image"}).sort(
                [("created_at", DESCENDING), ("id", ASCENDING)]).limit(50)),
            "名称模糊搜索": lambda: list(assets.find({"archived_at": None, "name": {"$regex": "男人", "$options": "i"}}).limit(50)),
            "无标签": lambda: list(assets.find({"archived_at": None, "tags": {}}).limit(50)),
            "深页跳页": lambda: list(assets.find({"archived_at": None}).sort(
                [("created_at", DESCENDING), ("id", ASCENDING)]).skip(args.count - 50).limit(50)),
        }
        print(f"测试库：{database_name}，合成素材：{args.count}（结束后自动删除）")
        for name, operation in queries.items():
            operation()
            print(f"{name}: P95 {measure(operation):.1f} ms")
    finally:
        client.drop_database(database_name)
        client.close()


if __name__ == "__main__":
    main()
