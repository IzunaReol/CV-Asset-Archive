import io
import json
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


def _stem(value: str) -> str:
    return Path(PurePosixPath(value).name).stem.casefold()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _box(x: float, y: float, width: float, height: float) -> dict[str, float]:
    left, top = _clamp(x), _clamp(y)
    return {
        "x": left,
        "y": top,
        "width": max(0.0, min(1.0 - left, width)),
        "height": max(0.0, min(1.0 - top, height)),
    }


def parse_coco_overlay(content: bytes, image_name: str) -> dict[str, Any]:
    data = json.loads(content.decode("utf-8-sig"))
    if not {"images", "annotations", "categories"}.issubset(data):
        raise ValueError("JSON is not a valid COCO dataset")
    matches = [
        item
        for item in data["images"]
        if _stem(str(item.get("file_name", ""))) == _stem(image_name)
    ]
    if not matches and len(data["images"]) == 1:
        matches = data["images"]
    if not matches:
        return {"format": "COCO", "matched": False, "items": []}
    image = matches[0]
    width, height = float(image.get("width") or 0), float(image.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("COCO image width and height are required")
    categories = {
        item.get("id"): str(item.get("name", item.get("id"))) for item in data["categories"]
    }
    items = []
    for annotation in data["annotations"]:
        if annotation.get("image_id") != image.get("id"):
            continue
        bbox = annotation.get("bbox")
        item: dict[str, Any] = {
            "id": str(annotation.get("id", len(items))),
            "label": categories.get(
                annotation.get("category_id"), str(annotation.get("category_id", "未知"))
            ),
        }
        if isinstance(bbox, list) and len(bbox) == 4:
            item["bbox"] = _box(
                float(bbox[0]) / width,
                float(bbox[1]) / height,
                float(bbox[2]) / width,
                float(bbox[3]) / height,
            )
        if annotation.get("score") is not None:
            item["confidence"] = float(annotation["score"])
        segmentation = annotation.get("segmentation")
        if isinstance(segmentation, list):
            polygons = []
            for polygon in segmentation:
                if not isinstance(polygon, list) or len(polygon) < 6 or len(polygon) % 2:
                    continue
                polygons.append(
                    [
                        {
                            "x": _clamp(float(polygon[index]) / width),
                            "y": _clamp(float(polygon[index + 1]) / height),
                        }
                        for index in range(0, len(polygon), 2)
                    ]
                )
            if polygons:
                item["polygons"] = polygons
                if "bbox" not in item:
                    points = [point for polygon in polygons for point in polygon]
                    xs = [point["x"] for point in points]
                    ys = [point["y"] for point in points]
                    item["bbox"] = _box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
        if "bbox" not in item:
            continue
        items.append(item)
    ignored = sum(
        1
        for annotation in data["annotations"]
        if annotation.get("image_id") == image.get("id")
        and not (
            isinstance(annotation.get("bbox"), list)
            and len(annotation.get("bbox")) == 4
            or isinstance(annotation.get("segmentation"), list)
            and bool(annotation.get("segmentation"))
        )
    )
    return {
        "format": "COCO",
        "matched": True,
        "image": image.get("file_name"),
        "items": items,
        "ignored_shapes": ignored,
    }


def _xml_root(content: bytes) -> ET.Element:
    if len(content) > 50 * 1024 * 1024:
        raise ValueError("XML annotation file exceeds 50 MB")
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise ValueError("XML annotation file is invalid") from exc


def xml_annotation_format(content: bytes) -> str | None:
    root = _xml_root(content)
    if root.tag == "annotations" and root.findall("image"):
        return "CVAT Images"
    if root.tag == "annotation" and root.find("filename") is not None:
        return "Pascal VOC"
    return None


def _polygon_points(value: str, width: float, height: float) -> list[dict[str, float]]:
    points = []
    for point in value.split(";"):
        x, separator, y = point.partition(",")
        if not separator:
            continue
        points.append({"x": _clamp(float(x) / width), "y": _clamp(float(y) / height)})
    return points if len(points) >= 3 else []


def parse_voc_overlay(content: bytes, image_name: str) -> dict[str, Any]:
    root = _xml_root(content)
    filename = (root.findtext("filename") or "").strip()
    if filename and _stem(filename) != _stem(image_name):
        return {"format": "Pascal VOC", "matched": False, "items": []}
    width = float(root.findtext("size/width") or 0)
    height = float(root.findtext("size/height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("Pascal VOC image width and height are required")
    items = []
    ignored = 0
    for index, obj in enumerate(root.findall("object")):
        label = (obj.findtext("name") or "未知").strip()
        box = obj.find("bndbox")
        polygon = obj.find("polygon")
        if box is not None:
            left = float(box.findtext("xmin") or 0)
            top = float(box.findtext("ymin") or 0)
            right = float(box.findtext("xmax") or 0)
            bottom = float(box.findtext("ymax") or 0)
            items.append(
                {
                    "id": f"voc:{index}",
                    "label": label,
                    "bbox": _box(
                        left / width, top / height, (right - left) / width, (bottom - top) / height
                    ),
                }
            )
        elif polygon is not None:
            points = []
            for point in polygon.findall("pt"):
                points.append(
                    {
                        "x": _clamp(float(point.findtext("x") or 0) / width),
                        "y": _clamp(float(point.findtext("y") or 0) / height),
                    }
                )
            if len(points) >= 3:
                xs, ys = [p["x"] for p in points], [p["y"] for p in points]
                items.append(
                    {
                        "id": f"voc:{index}",
                        "label": label,
                        "bbox": _box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                        "polygons": [points],
                    }
                )
            else:
                ignored += 1
        else:
            ignored += 1
    return {
        "format": "Pascal VOC",
        "matched": True,
        "image": filename or image_name,
        "items": items,
        "ignored_shapes": ignored,
    }


def parse_cvat_xml_overlay(content: bytes, image_name: str) -> dict[str, Any]:
    root = _xml_root(content)
    image = next(
        (
            item
            for item in root.findall("image")
            if _stem(item.get("name", "")) == _stem(image_name)
        ),
        None,
    )
    if image is None:
        return {"format": "CVAT Images", "matched": False, "items": []}
    width, height = float(image.get("width", 0)), float(image.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError("CVAT image width and height are required")
    items = []
    ignored = 0
    for index, shape in enumerate(list(image)):
        label = shape.get("label", "未知")
        if shape.tag == "box":
            left, top = float(shape.get("xtl", 0)), float(shape.get("ytl", 0))
            right, bottom = float(shape.get("xbr", 0)), float(shape.get("ybr", 0))
            items.append(
                {
                    "id": f"cvat:{index}",
                    "label": label,
                    "bbox": _box(
                        left / width, top / height, (right - left) / width, (bottom - top) / height
                    ),
                }
            )
        elif shape.tag == "polygon":
            points = _polygon_points(shape.get("points", ""), width, height)
            if points:
                xs, ys = [p["x"] for p in points], [p["y"] for p in points]
                items.append(
                    {
                        "id": f"cvat:{index}",
                        "label": label,
                        "bbox": _box(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)),
                        "polygons": [points],
                    }
                )
            else:
                ignored += 1
        else:
            ignored += 1
    return {
        "format": "CVAT Images",
        "matched": True,
        "image": image.get("name"),
        "items": items,
        "ignored_shapes": ignored,
    }


def annotation_document_metadata(content: bytes, filename: str) -> dict[str, Any] | None:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".json":
        try:
            data = json.loads(content.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeError):
            return None
        if not {"images", "annotations", "categories"}.issubset(data):
            return None
        categories = [str(item.get("name", item.get("id"))) for item in data["categories"]]
        supported = sum(
            1
            for item in data["annotations"]
            if isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4
        )
        polygon_count = sum(
            1
            for item in data["annotations"]
            if isinstance(item.get("segmentation"), list) and item["segmentation"]
        )
        recognized = sum(
            1
            for item in data["annotations"]
            if (isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4)
            or (isinstance(item.get("segmentation"), list) and bool(item["segmentation"]))
        )
        annotated_image_ids = {
            item.get("image_id")
            for item in data["annotations"]
            if (isinstance(item.get("bbox"), list) and len(item["bbox"]) == 4)
            or (isinstance(item.get("segmentation"), list) and bool(item["segmentation"]))
        }
        return {
            "annotation_format": "COCO",
            "image_refs": [
                str(item.get("file_name", ""))
                for item in data["images"]
                if item.get("file_name") and item.get("id") in annotated_image_ids
            ],
            "classes": categories,
            "shape_stats": {
                "boxes": supported,
                "polygons": polygon_count,
                "ignored": max(0, len(data["annotations"]) - recognized),
            },
        }
    if suffix == ".xml":
        fmt = xml_annotation_format(content)
        if fmt == "Pascal VOC":
            root = _xml_root(content)
            refs = (
                [(root.findtext("filename") or Path(filename).stem).strip()]
                if any(
                    item.find("bndbox") is not None or item.find("polygon") is not None
                    for item in root.findall("object")
                )
                else []
            )
            classes = sorted(
                {(item.findtext("name") or "未知").strip() for item in root.findall("object")}
            )
            boxes = sum(1 for item in root.findall("object") if item.find("bndbox") is not None)
            polygons = sum(1 for item in root.findall("object") if item.find("polygon") is not None)
            return {
                "annotation_format": fmt,
                "image_refs": refs,
                "classes": classes,
                "shape_stats": {
                    "boxes": boxes,
                    "polygons": polygons,
                    "ignored": max(0, len(root.findall("object")) - boxes - polygons),
                },
            }
        if fmt == "CVAT Images":
            root = _xml_root(content)
            images = root.findall("image")
            shapes = [shape for image in images for shape in list(image)]
            annotated_images = [
                image
                for image in images
                if any(shape.tag in {"box", "polygon"} for shape in list(image))
            ]
            return {
                "annotation_format": fmt,
                "image_refs": [
                    item.get("name", "") for item in annotated_images if item.get("name")
                ],
                "classes": sorted({shape.get("label", "未知") for shape in shapes}),
                "shape_stats": {
                    "boxes": sum(1 for shape in shapes if shape.tag == "box"),
                    "polygons": sum(1 for shape in shapes if shape.tag == "polygon"),
                    "ignored": sum(1 for shape in shapes if shape.tag not in {"box", "polygon"}),
                },
            }
    return None


def _yolo_classes(archive: zipfile.ZipFile) -> list[str]:
    names = archive.namelist()
    classes_file = next(
        (
            name
            for name in names
            if PurePosixPath(name).name.casefold() in {"classes.txt", "obj.names"}
        ),
        None,
    )
    if classes_file:
        return [
            line.strip()
            for line in archive.read(classes_file)
            .decode("utf-8-sig", errors="replace")
            .splitlines()
            if line.strip()
        ]
    yaml_file = next(
        (
            name
            for name in names
            if PurePosixPath(name).name.casefold() in {"data.yaml", "dataset.yaml"}
        ),
        None,
    )
    if yaml_file:
        text = archive.read(yaml_file).decode("utf-8-sig", errors="replace")
        marker = text.find("names:")
        if marker >= 0:
            value = text[marker + 6 :].splitlines()[0].strip()
            if value.startswith("[") and value.endswith("]"):
                return [part.strip().strip("'\"") for part in value[1:-1].split(",")]
            result = []
            for line in text[marker + 6 :].splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if ":" not in stripped or not stripped.split(":", 1)[0].isdigit():
                    break
                result.append(stripped.split(":", 1)[1].strip().strip("'\""))
            return result
    return []


def parse_yolo_overlay(content: bytes, image_name: str) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        label_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".txt")
            and PurePosixPath(name).name.casefold() != "classes.txt"
        ]
        label_file = next(
            (name for name in label_files if _stem(name) == _stem(image_name)),
            None,
        )
        if label_file is None and len(label_files) == 1:
            label_file = label_files[0]
        if not label_file:
            return {"format": "YOLO", "matched": False, "items": []}
        classes = _yolo_classes(archive)
        items = []
        for index, line in enumerate(
            archive.read(label_file).decode("utf-8-sig", errors="replace").splitlines()
        ):
            parts = line.split()
            if len(parts) < 5:
                continue
            class_id = int(float(parts[0]))
            center_x, center_y, width, height = map(float, parts[1:5])
            item: dict[str, Any] = {
                "id": f"{PurePosixPath(label_file).name}:{index + 1}",
                "label": classes[class_id] if 0 <= class_id < len(classes) else str(class_id),
                "bbox": _box(center_x - width / 2, center_y - height / 2, width, height),
            }
            if len(parts) > 5:
                item["confidence"] = float(parts[5])
            items.append(item)
        return {
            "format": "YOLO",
            "matched": True,
            "image": image_name,
            "label_file": label_file,
            "items": items,
        }


def parse_yolo_text(
    content: bytes, image_name: str, classes: list[str] | None = None
) -> dict[str, Any]:
    items = []
    class_names = classes or []
    for index, line in enumerate(content.decode("utf-8-sig", errors="replace").splitlines()):
        parts = line.split()
        if len(parts) < 5:
            continue
        class_id = int(float(parts[0]))
        center_x, center_y, width, height = map(float, parts[1:5])
        item: dict[str, Any] = {
            "id": f"{Path(image_name).stem}.txt:{index + 1}",
            "label": class_names[class_id] if 0 <= class_id < len(class_names) else str(class_id),
            "bbox": _box(center_x - width / 2, center_y - height / 2, width, height),
        }
        if len(parts) > 5:
            item["confidence"] = float(parts[5])
        items.append(item)
    return {"format": "YOLO", "matched": True, "image": image_name, "items": items}


def parse_annotation_overlay(
    content: bytes, filename: str, image_name: str, classes: list[str] | None = None
) -> dict[str, Any]:
    suffix = Path(filename).suffix.casefold()
    if suffix == ".json":
        return parse_coco_overlay(content, image_name)
    if suffix == ".zip":
        return parse_yolo_overlay(content, image_name)
    if suffix == ".txt":
        return parse_yolo_text(content, image_name, classes)
    if suffix == ".xml":
        fmt = xml_annotation_format(content)
        if fmt == "Pascal VOC":
            return parse_voc_overlay(content, image_name)
        if fmt == "CVAT Images":
            return parse_cvat_xml_overlay(content, image_name)
        raise ValueError("Unsupported XML annotation format")
    raise ValueError("Unsupported annotation preview format")
