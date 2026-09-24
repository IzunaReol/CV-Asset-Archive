import hashlib
import io
import json
import mimetypes
import os
import subprocess
import tempfile
import threading
import uuid
import zipfile
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path

from celery import Celery
from minio import Minio
from PIL import Image, ImageDraw
from pymongo import MongoClient

from backend.app.annotation_overlay import annotation_document_metadata

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "cv_archive")
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "cv-assets")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
WORKER_TEMP_DIR = Path(os.getenv("WORKER_TEMP_DIR", tempfile.gettempdir()))

app = Celery("cv-archive-worker", broker=REDIS_URL, backend=REDIS_URL)
database = MongoClient(MONGODB_URI, tz_aware=True)[MONGODB_DATABASE]
storage = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def failure_details(exc: Exception) -> dict[str, str]:
    if isinstance(exc, PermissionError):
        return {"code": "PROCESS_PERMISSION_DENIED", "message": "处理目录没有读写权限"}
    return {"code": "PROCESS_FAILED", "message": str(exc)[:1000]}


def fail_job(job_id: str, exc: Exception) -> None:
    database.jobs.update_one(
        {"id": job_id},
        {
            "$set": {
                "state": "failed",
                "error": failure_details(exc),
                "updated_at": utcnow(),
            }
        },
    )


def job_cancelled(job_id: str) -> bool:
    job = database.jobs.find_one({"id": job_id}, {"state": 1, "cancel_requested": 1})
    return bool(job and (job.get("state") == "cancelled" or job.get("cancel_requested")))


def with_job_heartbeat(task_function):
    @wraps(task_function)
    def wrapped(job_id: str, *args, **kwargs):
        stopped = threading.Event()

        def pulse() -> None:
            while not stopped.wait(15):
                timestamp = utcnow()
                database.jobs.update_one(
                    {"id": job_id, "state": "running"},
                    {"$set": {"heartbeat_at": timestamp, "updated_at": timestamp}},
                )

        heartbeat = threading.Thread(target=pulse, daemon=True)
        heartbeat.start()
        try:
            return task_function(job_id, *args, **kwargs)
        finally:
            stopped.set()
            heartbeat.join(timeout=1)

    return wrapped


def fail_asset(asset_id: str, exc: Exception) -> None:
    database.assets.update_one(
        {"id": asset_id},
        {
            "$set": {
                "status": "failed",
                "processing_error": failure_details(exc),
                "updated_at": utcnow(),
            }
        },
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_object(object_key: str) -> str:
    digest = hashlib.sha256()
    response = storage.get_object(MINIO_BUCKET, object_key)
    try:
        for chunk in iter(lambda: response.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    finally:
        response.close()
        response.release_conn()
    return digest.hexdigest()


def download_object(object_key: str, target: Path) -> None:
    """Streams an object to its final path without MinIO's extra .part file."""
    response = storage.get_object(MINIO_BUCKET, object_key)
    try:
        with target.open("wb") as output:
            for chunk in iter(lambda: response.read(4 * 1024 * 1024), b""):
                output.write(chunk)
    finally:
        response.close()
        response.release_conn()


def image_metadata(path: Path, asset_id: str) -> tuple[dict, str]:
    preview_key = f"previews/{asset_id}.jpg"
    preview_path = path.with_suffix(".preview.jpg")
    with Image.open(path) as image:
        media = {"width": image.width, "height": image.height, "format": image.format}
        image.thumbnail((1280, 1280))
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(preview_path, "JPEG", quality=84, optimize=True)
    storage.fput_object(MINIO_BUCKET, preview_key, str(preview_path), content_type="image/jpeg")
    return media, preview_key


def video_metadata(path: Path, asset_id: str) -> tuple[dict, str]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height,codec_name",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(probe.stdout)
    video_stream = next((stream for stream in data.get("streams", []) if stream.get("width")), {})
    media = {
        "duration": float(data.get("format", {}).get("duration", 0)),
        "width": video_stream.get("width"),
        "height": video_stream.get("height"),
        "codec": video_stream.get("codec_name"),
    }
    preview_path = path.with_suffix(".preview.jpg")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "0",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=min(1280\\,iw):-2",
            str(preview_path),
        ],
        check=True,
        capture_output=True,
    )
    preview_key = f"previews/{asset_id}.jpg"
    storage.fput_object(MINIO_BUCKET, preview_key, str(preview_path), content_type="image/jpeg")
    return media, preview_key


def annotation_metadata(path: Path) -> dict:
    if path.suffix.lower() in {".json", ".xml"}:
        document = annotation_document_metadata(path.read_bytes(), path.name)
        if document:
            if document["annotation_format"] == "COCO":
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                document.update(
                    image_count=len(data["images"]),
                    annotation_count=len(data["annotations"]),
                )
            return document
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if {"images", "annotations", "categories"}.issubset(data):
            return {
                "annotation_format": "COCO",
                "image_count": len(data["images"]),
                "annotation_count": len(data["annotations"]),
            }
        return {"annotation_format": "JSON"}
    if path.suffix.lower() in {".txt", ".xml", ".yaml", ".yml", ".csv"}:
        return {
            "annotation_format": {
                ".txt": "TXT / YOLO",
                ".xml": "XML / CVAT / VOC",
                ".yaml": "YAML",
                ".yml": "YAML",
                ".csv": "CSV",
            }[path.suffix.lower()]
        }
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            labels = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".txt")
                and not name.lower().endswith("classes.txt")
                and Path(name).stem.casefold() not in {"train", "val", "test", "validation"}
            ]
            invalid = 0
            for name in labels:
                for line in archive.read(name).decode("utf-8", errors="replace").splitlines():
                    parts = line.split()
                    if len(parts) != 5:
                        invalid += 1
                        continue
                    try:
                        values = [float(value) for value in parts[1:]]
                        if any(value < 0 or value > 1 for value in values):
                            invalid += 1
                    except ValueError:
                        invalid += 1
            if not labels:
                raise ValueError("压缩包中没有 YOLO 标注文件")
            if invalid:
                raise ValueError(f"YOLO 压缩包包含 {invalid} 行无效标注")
            return {"annotation_format": "YOLO", "label_file_count": len(labels)}
    return {"annotation_format": path.suffix.lstrip(".").upper() or "UNKNOWN"}


def cvat_yolo_pairs(path: Path) -> list[tuple[str, str]]:
    if path.suffix.casefold() != ".zip":
        return []
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    with zipfile.ZipFile(path) as archive:
        images = {
            Path(name).stem.casefold(): name
            for name in archive.namelist()
            if Path(name).suffix.casefold() in image_suffixes
        }
        labels = {
            Path(name).stem.casefold(): name
            for name in archive.namelist()
            if name.lower().endswith(".txt")
            and Path(name).stem.casefold() not in {"classes", "train", "val", "test", "validation"}
        }
    return [(images[stem], labels[stem]) for stem in sorted(images.keys() & labels.keys())]


def yolo_class_names(yaml_content: bytes) -> list[str]:
    text = yaml_content.decode("utf-8-sig", errors="replace")
    marker = text.find("names:")
    if marker < 0:
        return []
    first_line = text[marker + 6 :].splitlines()[0].strip()
    if first_line.startswith("[") and first_line.endswith("]"):
        return [part.strip().strip("'\"") for part in first_line[1:-1].split(",")]
    result: list[str] = []
    for line in text[marker + 6 :].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator or not key.strip().isdigit():
            break
        result.append(value.strip().strip("'\""))
    return result


def yolo_archive_class_names(archive: zipfile.ZipFile) -> list[str]:
    names_file = next(
        (
            name
            for name in archive.namelist()
            if Path(name).name.casefold() in {"classes.txt", "obj.names"}
        ),
        None,
    )
    if names_file:
        return [
            line.strip()
            for line in archive.read(names_file).decode("utf-8-sig", errors="replace").splitlines()
            if line.strip()
        ]
    yaml_name = next(
        (
            name
            for name in archive.namelist()
            if Path(name).name.casefold() in {"data.yaml", "dataset.yaml"}
        ),
        None,
    )
    return yolo_class_names(archive.read(yaml_name)) if yaml_name else []


def import_cvat_yolo_bundle(path: Path, bundle: dict) -> dict:
    pairs = cvat_yolo_pairs(path)
    if not pairs:
        return {
            "detected": False,
            "image_count": 0,
            "annotation_count": 0,
            "relation_count": 0,
        }
    imported_images = imported_annotations = imported_relations = 0
    creator = database.users.find_one({"id": bundle.get("created_by")}, {"username": 1})
    creator_name = (creator or {}).get("username", "未知用户")
    with (
        zipfile.ZipFile(path) as archive,
        tempfile.TemporaryDirectory(prefix="cv-archive-cvat-", dir=WORKER_TEMP_DIR) as temp_dir,
    ):
        class_names = yolo_archive_class_names(archive)
        for image_entry, label_entry in pairs:
            image_import_key = f"{bundle['id']}:{image_entry}"
            image_asset = database.assets.find_one({"import_source.key": image_import_key})
            if image_asset is None:
                image_id = str(uuid.uuid4())
                image_bytes = archive.read(image_entry)
                image_name = Path(image_entry).name
                image_path = Path(temp_dir) / f"{image_id}-{image_name}"
                image_path.write_bytes(image_bytes)
                object_key = f"imports/{bundle['id']}/images/{image_id}/original"
                storage.put_object(
                    MINIO_BUCKET,
                    object_key,
                    io.BytesIO(image_bytes),
                    len(image_bytes),
                    content_type=mimetypes.guess_type(image_name)[0] or "application/octet-stream",
                )
                image_media, preview_key = image_metadata(image_path, image_id)
                timestamp = utcnow()
                image_asset = {
                    "id": image_id,
                    "name": image_name,
                    "type": "image",
                    "object_key": object_key,
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "size": len(image_bytes),
                    "mime_type": mimetypes.guess_type(image_name)[0] or "application/octet-stream",
                    "project": bundle.get("project", "未分类"),
                    "remark": "",
                    "tags": dict(bundle.get("tags", {})),
                    "status": "ready",
                    "media": {
                        **image_media,
                        "extension": Path(image_name).suffix.casefold(),
                    },
                    "preview_key": preview_key,
                    "created_by": bundle["created_by"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "archived_at": None,
                    "import_source": {
                        "bundle_asset_id": bundle["id"],
                        "entry": image_entry,
                        "key": image_import_key,
                    },
                }
                database.assets.insert_one(image_asset)
                imported_images += 1

            annotation_import_key = f"{bundle['id']}:{label_entry}"
            annotation_asset = database.assets.find_one(
                {"import_source.key": annotation_import_key}
            )
            if annotation_asset is None:
                annotation_id = str(uuid.uuid4())
                label_bytes = archive.read(label_entry)
                annotation_name = Path(label_entry).name
                object_key = f"imports/{bundle['id']}/annotations/{annotation_id}/original"
                storage.put_object(
                    MINIO_BUCKET,
                    object_key,
                    io.BytesIO(label_bytes),
                    len(label_bytes),
                    content_type="text/plain",
                )
                timestamp = utcnow()
                annotation_asset = {
                    "id": annotation_id,
                    "name": annotation_name,
                    "type": "annotation",
                    "object_key": object_key,
                    "sha256": hashlib.sha256(label_bytes).hexdigest(),
                    "size": len(label_bytes),
                    "mime_type": "text/plain",
                    "project": bundle.get("project", "未分类"),
                    "remark": "",
                    "tags": {**bundle.get("tags", {}), "annotation_format": "YOLO"},
                    "status": "ready",
                    "media": {
                        "annotation_format": "YOLO",
                        "label_file_count": 1,
                        "extension": Path(annotation_name).suffix.casefold(),
                        "classes": class_names,
                    },
                    "preview_key": None,
                    "created_by": bundle["created_by"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "archived_at": None,
                    "import_source": {
                        "bundle_asset_id": bundle["id"],
                        "entry": label_entry,
                        "key": annotation_import_key,
                    },
                }
                database.assets.insert_one(annotation_asset)
                imported_annotations += 1

            existing_relation = database.relations.find_one(
                {"source_id": annotation_asset["id"], "target_id": image_asset["id"], "relation_type": "annotates", "status": "active"}
            )
            if existing_relation is None:
                database.relations.insert_one({
                    "id": str(uuid.uuid4()), "source_id": annotation_asset["id"],
                    "target_id": image_asset["id"], "relation_type": "annotates",
                    "provenance": {"source": "cvat_import", "bundle_asset_id": bundle["id"]},
                    "revision": 1, "status": "active", "created_by": bundle["created_by"],
                    "created_by_name": creator_name, "created_at": utcnow(),
                })
                imported_relations += 1
    return {
        "detected": True,
        "annotation_format": "YOLO",
        "image_count": imported_images,
        "annotation_count": imported_annotations,
        "relation_count": imported_relations,
        "pair_count": len(pairs),
        "unmatched_count": 0,
        "conflict_count": 0,
    }


def _rollback_bundle(bundle_id: str) -> None:
    assets = list(database.assets.find({"import_source.bundle_asset_id": bundle_id}))
    for asset in assets:
        for key in (asset.get("object_key"), asset.get("preview_key")):
            if key:
                try:
                    storage.remove_object(MINIO_BUCKET, key)
                except Exception:
                    pass
    asset_ids = [asset["id"] for asset in assets]
    database.relations.delete_many(
        {"provenance.bundle_asset_id": bundle_id, "provenance.source": "cvat_import"}
    )
    if asset_ids:
        database.assets.delete_many({"id": {"$in": asset_ids}})


def inspect_supported_bundle(path: Path) -> dict:
    image_suffixes = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 100000:
            raise ValueError("压缩包文件数量超过 100000 个")
        images = [
            name for name in archive.namelist() if Path(name).suffix.casefold() in image_suffixes
        ]
        documents = []
        detected_formats = set()
        for name in archive.namelist():
            if Path(name).suffix.casefold() not in {".xml", ".json"}:
                continue
            metadata = annotation_document_metadata(archive.read(name), name)
            if metadata:
                documents.append({"entry": name, "metadata": metadata})
                detected_formats.add(metadata["annotation_format"])
        yolo_pairs = cvat_yolo_pairs(path)
        if yolo_pairs:
            detected_formats.add("YOLO")
        if len(detected_formats) > 1:
            raise ValueError("压缩包包含多种标注格式，请分别上传")
        if not detected_formats:
            return {"detected": False, "images": images, "documents": [], "format": None}
        return {
            "detected": True,
            "images": images,
            "documents": documents,
            "format": next(iter(detected_formats)),
            "yolo_pairs": yolo_pairs,
        }


def import_cvat_annotation_bundle(path: Path, bundle: dict) -> dict:
    manifest = inspect_supported_bundle(path)
    if not manifest["detected"]:
        return {"detected": False, "image_count": 0, "annotation_count": 0, "relation_count": 0}
    bundle_id = bundle["id"]
    try:
        if manifest["format"] == "YOLO":
            return import_cvat_yolo_bundle(path, bundle)
        creator = database.users.find_one({"id": bundle.get("created_by")}, {"username": 1})
        creator_name = (creator or {}).get("username", "未知用户")
        imported_images = imported_annotations = imported_relations = 0
        unmatched = conflicts = 0
        with (
            zipfile.ZipFile(path) as archive,
            tempfile.TemporaryDirectory(prefix="cv-archive-cvat-", dir=WORKER_TEMP_DIR) as temp_dir,
        ):
            image_entries_by_stem: dict[str, list[str]] = {}
            for entry in manifest["images"]:
                image_entries_by_stem.setdefault(Path(entry).stem.casefold(), []).append(entry)
            conflicts = sum(1 for entries in image_entries_by_stem.values() if len(entries) > 1)
            annotation_specs = []
            claimed_stems: set[str] = set()
            for document in manifest["documents"]:
                metadata = document["metadata"]
                matches = []
                for image_ref in metadata.get("image_refs", []):
                    stem = Path(image_ref).stem.casefold()
                    entries = image_entries_by_stem.get(stem, [])
                    if len(entries) == 1:
                        matches.append(entries[0])
                        claimed_stems.add(stem)
                    elif len(entries) > 1:
                        conflicts += 1
                    else:
                        unmatched += 1
                annotation_specs.append({**document, "matches": list(dict.fromkeys(matches))})
            claimers: dict[str, set[int]] = {}
            for index, spec in enumerate(annotation_specs):
                for entry in spec["matches"]:
                    claimers.setdefault(Path(entry).stem.casefold(), set()).add(index)
            conflicting_claims = {stem for stem, indexes in claimers.items() if len(indexes) > 1}
            conflicts += len(conflicting_claims)
            for spec in annotation_specs:
                spec["matches"] = [
                    entry
                    for entry in spec["matches"]
                    if Path(entry).stem.casefold() not in conflicting_claims
                ]
            unmatched += sum(1 for stem in image_entries_by_stem if stem not in claimed_stems)

            image_assets = {}
            for image_entry in manifest["images"]:
                image_bytes = archive.read(image_entry)
                image_name = Path(image_entry).name
                image_id = str(uuid.uuid4())
                image_path = Path(temp_dir) / f"{image_id}-{image_name}"
                image_path.write_bytes(image_bytes)
                object_key = f"imports/{bundle_id}/images/{image_id}/original"
                storage.put_object(
                    MINIO_BUCKET,
                    object_key,
                    io.BytesIO(image_bytes),
                    len(image_bytes),
                    content_type=mimetypes.guess_type(image_name)[0] or "application/octet-stream",
                )
                image_media, preview_key = image_metadata(image_path, image_id)
                timestamp = utcnow()
                asset = {
                    "id": image_id,
                    "name": image_name,
                    "type": "image",
                    "object_key": object_key,
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "size": len(image_bytes),
                    "mime_type": mimetypes.guess_type(image_name)[0] or "application/octet-stream",
                    "project": bundle.get("project", "未分类"),
                    "remark": "",
                    "tags": dict(bundle.get("tags", {})),
                    "status": "ready",
                    "media": {**image_media, "extension": Path(image_name).suffix.casefold()},
                    "preview_key": preview_key,
                    "created_by": bundle["created_by"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "archived_at": None,
                    "import_source": {
                        "bundle_asset_id": bundle_id,
                        "entry": image_entry,
                        "key": f"{bundle_id}:{image_entry}",
                    },
                }
                database.assets.insert_one(asset)
                image_assets[image_entry] = asset
                imported_images += 1

            for spec in annotation_specs:
                entry = spec["entry"]
                content = archive.read(entry)
                metadata = spec["metadata"]
                annotation_id = str(uuid.uuid4())
                annotation_name = Path(entry).name
                object_key = f"imports/{bundle_id}/annotations/{annotation_id}/original"
                content_type = (
                    "application/json"
                    if Path(entry).suffix.casefold() == ".json"
                    else "application/xml"
                )
                storage.put_object(
                    MINIO_BUCKET,
                    object_key,
                    io.BytesIO(content),
                    len(content),
                    content_type=content_type,
                )
                timestamp = utcnow()
                annotation_asset = {
                    "id": annotation_id,
                    "name": annotation_name,
                    "type": "annotation",
                    "object_key": object_key,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "mime_type": content_type,
                    "project": bundle.get("project", "未分类"),
                    "remark": "",
                    "tags": {
                        **bundle.get("tags", {}),
                        "annotation_format": metadata["annotation_format"],
                    },
                    "status": "ready",
                    "media": {**metadata, "extension": Path(annotation_name).suffix.casefold()},
                    "preview_key": None,
                    "created_by": bundle["created_by"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "archived_at": None,
                    "import_source": {
                        "bundle_asset_id": bundle_id,
                        "entry": entry,
                        "key": f"{bundle_id}:{entry}",
                    },
                }
                database.assets.insert_one(annotation_asset)
                imported_annotations += 1
                for image_entry in spec["matches"]:
                    image_asset = image_assets[image_entry]
                    database.relations.insert_one({
                        "id": str(uuid.uuid4()), "source_id": annotation_id,
                        "target_id": image_asset["id"], "relation_type": "annotates",
                        "provenance": {"source": "cvat_import", "bundle_asset_id": bundle_id},
                        "revision": 1, "status": "active", "created_by": bundle["created_by"],
                        "created_by_name": creator_name, "created_at": utcnow(),
                    })
                    imported_relations += 1
        return {
            "detected": True,
            "annotation_format": manifest["format"],
            "image_count": imported_images,
            "annotation_count": imported_annotations,
            "relation_count": imported_relations,
            "pair_count": imported_relations,
            "unmatched_count": unmatched,
            "conflict_count": conflicts,
        }
    except Exception:
        _rollback_bundle(bundle_id)
        raise


def yolo_preview(path: Path, asset_id: str) -> str | None:
    if path.suffix.lower() != ".zip":
        return None
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        images = {
            Path(name).stem: name
            for name in names
            if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        }
        label_name = next(
            (name for name in names if name.lower().endswith(".txt") and Path(name).stem in images),
            None,
        )
        if label_name is None:
            return None
        with Image.open(io.BytesIO(archive.read(images[Path(label_name).stem]))) as source:
            image = source.convert("RGB")
        draw = ImageDraw.Draw(image)
        width, height = image.size
        for row in archive.read(label_name).decode("utf-8", errors="replace").splitlines():
            parts = row.split()
            if len(parts) != 5:
                continue
            class_id, center_x, center_y, box_width, box_height = map(float, parts)
            left = (center_x - box_width / 2) * width
            top = (center_y - box_height / 2) * height
            right = (center_x + box_width / 2) * width
            bottom = (center_y + box_height / 2) * height
            line_width = max(2, round(min(width, height) / 250))
            draw.rectangle((left, top, right, bottom), outline="#ff5a36", width=line_width)
            draw.text((left + 3, max(0, top - 14)), str(int(class_id)), fill="#ff5a36")
        image.thumbnail((1280, 1280))
        preview_path = path.with_suffix(".preview.jpg")
        image.save(preview_path, "JPEG", quality=86, optimize=True)
    preview_key = f"previews/{asset_id}.jpg"
    storage.fput_object(MINIO_BUCKET, preview_key, str(preview_path), content_type="image/jpeg")
    return preview_key


@app.task(
    name="worker.tasks.process_asset",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=3,
)
@with_job_heartbeat
def process_asset(job_id: str, asset_id: str) -> None:
    try:
        WORKER_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        database.jobs.update_one(
            {"id": job_id},
            {"$set": {"state": "running", "progress": 10, "updated_at": utcnow()}},
        )
        asset = database.assets.find_one({"id": asset_id})
        if asset is None:
            raise ValueError("素材不存在")
        stat = storage.stat_object(MINIO_BUCKET, asset["object_key"])
        media = {
            "etag": stat.etag,
            "last_modified": stat.last_modified,
            "content_type": stat.content_type,
            "extension": Path(asset["name"]).suffix.lower(),
        }
        preview_key = None
        bundle_import = None
        if asset["type"] == "model":
            digest = sha256_object(asset["object_key"])
        else:
            with tempfile.TemporaryDirectory(
                prefix="cv-archive-process-",
                dir=WORKER_TEMP_DIR,
                ignore_cleanup_errors=True,
            ) as temp_dir:
                source_path = Path(temp_dir) / (Path(asset["name"]).name or "asset.bin")
                download_object(asset["object_key"], source_path)
                digest = sha256_file(source_path)
                if asset["type"] == "image":
                    details, preview_key = image_metadata(source_path, asset_id)
                    media.update(details)
                elif asset["type"] == "video":
                    details, preview_key = video_metadata(source_path, asset_id)
                    media.update(details)
                elif asset["type"] == "annotation":
                    media.update(annotation_metadata(source_path))
                    preview_key = yolo_preview(source_path, asset_id)
                elif asset["type"] == "image_annotation":
                    bundle_import = import_cvat_annotation_bundle(source_path, asset)
                    if not bundle_import["detected"]:
                        raise ValueError("压缩包中未识别到支持的图片标注格式")

        if asset["type"] == "image_annotation" and bundle_import:
            storage.remove_object(MINIO_BUCKET, asset["object_key"])
            database.assets.delete_one({"id": asset_id})
            database.jobs.update_one(
                {"id": job_id},
                {
                    "$set": {
                        "state": "succeeded",
                        "progress": 100,
                        "result": {
                            "asset_id": None,
                            "source_asset_id": asset_id,
                            "source_asset_deleted": True,
                            "bundle_import": bundle_import,
                        },
                        "updated_at": utcnow(),
                    }
                },
            )
            return

        duplicate = database.assets.find_one(
            {
                "id": {"$ne": asset_id},
                "sha256": digest,
                "size": asset["size"],
                "archived_at": None,
            }
        )
        object_key = asset["object_key"]
        if duplicate and duplicate["object_key"] != object_key:
            storage.remove_object(MINIO_BUCKET, object_key)
            object_key = duplicate["object_key"]
        database.assets.update_one(
            {"id": asset_id},
            {
                "$set": {
                    "media": media,
                    "preview_key": preview_key,
                    "sha256": digest,
                    "object_key": object_key,
                    "reuses_asset_id": duplicate["id"]
                    if duplicate
                    else asset.get("reuses_asset_id"),
                    "status": "ready",
                    "processing_error": None,
                }
            },
        )
        database.jobs.update_one(
            {"id": job_id},
            {
                "$set": {
                    "state": "succeeded",
                    "progress": 100,
                    "result": {"asset_id": asset_id, "bundle_import": bundle_import},
                    "updated_at": utcnow(),
                }
            },
        )
    except Exception as exc:
        fail_job(job_id, exc)
        fail_asset(asset_id, exc)
        raise


@app.task(
    name="worker.tasks.build_export",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=3,
)
@with_job_heartbeat
def build_export(job_id: str) -> None:
    try:
        WORKER_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        job = database.jobs.find_one({"id": job_id})
        if job is None:
            raise ValueError("任务不存在")
        if job_cancelled(job_id):
            return
        claimed = database.jobs.update_one(
            {"id": job_id, "state": {"$ne": "cancelled"}},
            {"$set": {"state": "running", "progress": 2, "updated_at": utcnow()}},
        )
        if not claimed.modified_count or job_cancelled(job_id):
            return
        selection_id = job["input"].get("selection_id")
        if selection_id:
            selection = database.asset_selection_sets.find_one({"id": selection_id})
            if selection is None:
                raise ValueError("导出选择范围已过期")
            excluded = set(job["input"].get("excluded_ids", []))
            asset_ids = [item for item in selection["asset_ids"] if item not in excluded]
        else:
            asset_ids = job["input"]["asset_ids"]
        asset_query = {"id": {"$in": asset_ids}, "archived_at": None}
        asset_count = database.assets.count_documents(asset_query)
        if not asset_count:
            raise ValueError("没有可导出的素材")
        assets = database.assets.find(asset_query)
        with tempfile.TemporaryDirectory(
            prefix="cv-archive-export-", dir=WORKER_TEMP_DIR
        ) as temp_dir:
            zip_path = Path(temp_dir) / f"{job_id}.zip"
            used_names: set[str] = set()
            with zipfile.ZipFile(
                zip_path, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
            ) as archive:
                for index, asset in enumerate(assets):
                    if job_cancelled(job_id):
                        return
                    filename = Path(asset["name"]).name
                    if filename in used_names:
                        stem, suffix = os.path.splitext(filename)
                        filename = f"{stem}-{asset['id'][:8]}{suffix}"
                    used_names.add(filename)
                    response = storage.get_object(MINIO_BUCKET, asset["object_key"])
                    try:
                        with archive.open(filename, "w") as output:
                            for chunk in response.stream(1024 * 1024):
                                output.write(chunk)
                    finally:
                        response.close()
                        response.release_conn()
                    progress = 5 + int(((index + 1) / asset_count) * 85)
                    database.jobs.update_one(
                        {"id": job_id, "state": {"$ne": "cancelled"}},
                        {"$set": {"progress": progress, "updated_at": utcnow()}},
                    )
            if job_cancelled(job_id):
                return
            export_name = str(job.get("name") or job_id).replace("/", "_").replace("\\", "_")
            object_key = f"exports/{job_id}/{export_name}.zip"
            content_type = mimetypes.guess_type(zip_path.name)[0] or "application/zip"
            storage.fput_object(MINIO_BUCKET, object_key, str(zip_path), content_type=content_type)
        if job_cancelled(job_id):
            storage.remove_object(MINIO_BUCKET, object_key)
            return
        completed = database.jobs.update_one(
            {"id": job_id, "state": {"$ne": "cancelled"}},
            {
                "$set": {
                    "state": "succeeded",
                    "progress": 100,
                    "result": {"object_key": object_key, "asset_count": asset_count},
                    "updated_at": utcnow(),
                }
            },
        )
        if not completed.modified_count:
            storage.remove_object(MINIO_BUCKET, object_key)
    except Exception as exc:
        fail_job(job_id, exc)
        raise


@app.task(name="worker.tasks.empty_trash")
@with_job_heartbeat
def empty_trash(job_id: str) -> None:
    try:
        job = database.jobs.find_one({"id": job_id})
        if job is None:
            raise ValueError("任务不存在")
        database.jobs.update_one(
            {"id": job_id},
            {"$set": {"state": "running", "progress": 1, "updated_at": utcnow()}},
        )
        assets = list(database.assets.find({"archived_at": {"$ne": None}}))
        succeeded: list[str] = []
        failed: list[dict[str, str]] = []
        removed_keys: set[str] = set()
        for index, asset in enumerate(assets):
            asset_id = asset["id"]
            try:
                preview_key = asset.get("preview_key")
                if preview_key and preview_key != asset.get("object_key"):
                    if preview_key not in removed_keys:
                        storage.remove_object(MINIO_BUCKET, preview_key)
                        removed_keys.add(preview_key)
                object_key = asset.get("object_key")
                if object_key and object_key not in removed_keys:
                    active_references = database.assets.count_documents(
                        {"object_key": object_key, "archived_at": None}
                    )
                    if not active_references:
                        storage.remove_object(MINIO_BUCKET, object_key)
                        removed_keys.add(object_key)
                database.relations.delete_many(
                    {"$or": [{"source_id": asset_id}, {"target_id": asset_id}]}
                )
                database.collections.update_many(
                    {"asset_ids": asset_id}, {"$pull": {"asset_ids": asset_id}}
                )
                database.asset_versions.delete_many({"asset_id": asset_id})
                database.assets.delete_one({"id": asset_id})
                succeeded.append(asset_id)
            except Exception as exc:
                failed.append({"id": asset_id, "code": "DELETE_FAILED", "message": str(exc)[:200]})
            progress = 5 + int(((index + 1) / max(1, len(assets))) * 90)
            database.jobs.update_one(
                {"id": job_id}, {"$set": {"progress": progress, "updated_at": utcnow()}}
            )
        timestamp = utcnow()
        result = {"succeeded": succeeded, "failed": failed}
        database.jobs.update_one(
            {"id": job_id},
            {
                "$set": {
                    "state": "succeeded",
                    "progress": 100,
                    "result": result,
                    "updated_at": timestamp,
                }
            },
        )
        database.audit_logs.insert_one(
            {
                "id": str(uuid.uuid4()),
                "actor_id": job["owner_id"],
                "actor_username": job.get("input", {}).get("actor_username", "未知用户"),
                "action": "trash.emptied",
                "object_type": "asset",
                "object_id": "trash",
                "changes": {
                    "asset_ids": succeeded,
                    "count": len(succeeded),
                    "failed_count": len(failed),
                },
                "request_id": job.get("input", {}).get("request_id", "unknown"),
                "created_at": timestamp,
            }
        )
    except Exception as exc:
        fail_job(job_id, exc)
        raise
