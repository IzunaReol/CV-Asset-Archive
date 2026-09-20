import io
import json
import zipfile

import pytest
from backend.app.annotation_overlay import (
    annotation_document_metadata,
    parse_annotation_overlay,
    parse_coco_overlay,
    parse_yolo_overlay,
)


def test_parse_coco_overlay_matches_filename_and_normalizes_box():
    content = json.dumps(
        {
            "images": [
                {"id": 7, "file_name": "images/camera-01.jpg", "width": 1000, "height": 500}
            ],
            "categories": [{"id": 2, "name": "person"}],
            "annotations": [
                {
                    "id": 9,
                    "image_id": 7,
                    "category_id": 2,
                    "bbox": [100, 50, 200, 100],
                    "segmentation": [[100, 50, 300, 50, 300, 150]],
                }
            ],
        }
    ).encode()
    result = parse_coco_overlay(content, "camera-01.png")
    assert result["matched"] is True
    assert result["items"][0]["label"] == "person"
    assert result["items"][0]["bbox"] == {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2}
    assert result["items"][0]["polygons"][0][2] == {"x": 0.3, "y": 0.3}


def test_parse_yolo_overlay_uses_related_image_stem_and_classes():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("classes.txt", "person\ncar\n")
        archive.writestr("labels/camera-01.txt", "1 0.5 0.5 0.2 0.4\n")
    result = parse_yolo_overlay(output.getvalue(), "camera-01.jpg")
    assert result["matched"] is True
    assert result["items"][0]["label"] == "car"
    assert result["items"][0]["bbox"] == {"x": 0.4, "y": 0.3, "width": 0.2, "height": 0.4}


def test_parse_yolo_overlay_supports_cvat_obj_names():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("obj.names", "smoking\n")
        archive.writestr("obj_train_data/frame.txt", "0 0.5 0.5 0.2 0.2\n")
    result = parse_yolo_overlay(content.getvalue(), "frame.jpg")
    assert result["items"][0]["label"] == "smoking"


def test_single_yolo_label_file_uses_explicit_relation_as_fallback():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("labels/different-name.txt", "0 0.5 0.5 0.2 0.2\n")
    result = parse_yolo_overlay(output.getvalue(), "linked-image.jpg")
    assert result["matched"] is True
    assert len(result["items"]) == 1


def test_parse_extracted_yolo_txt_uses_saved_class_names():
    result = parse_annotation_overlay(
        b"0 0.5 0.5 0.4 0.2\n", "camera-01.txt", "camera-01.jpg", ["smoking"]
    )
    assert result["format"] == "YOLO"
    assert result["items"][0]["label"] == "smoking"
    assert result["items"][0]["bbox"] == {"x": 0.3, "y": 0.4, "width": 0.4, "height": 0.2}


def test_yolo_without_class_names_does_not_show_a_bare_numeric_label():
    result = parse_annotation_overlay(b"0 0.5 0.5 0.4 0.2\n", "camera-01.txt", "camera-01.jpg")
    assert result["items"][0]["label"] == "未命名类别"


def test_parse_pascal_voc_box_and_metadata():
    content = b"""<annotation><filename>frame.jpg</filename><size><width>200</width><height>100</height></size><object><name>smoking</name><bndbox><xmin>20</xmin><ymin>10</ymin><xmax>80</xmax><ymax>60</ymax></bndbox></object></annotation>"""
    result = parse_annotation_overlay(content, "frame.xml", "frame.jpg")
    assert result["format"] == "Pascal VOC"
    assert result["items"][0]["label"] == "smoking"
    assert result["items"][0]["bbox"] == {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.5}
    metadata = annotation_document_metadata(content, "frame.xml")
    assert metadata["image_refs"] == ["frame.jpg"]
    assert metadata["classes"] == ["smoking"]


def test_parse_cvat_images_box_polygon_and_ignored_shape():
    content = b"""<annotations><image id="0" name="images/frame.jpg" width="200" height="100"><box label="person" xtl="20" ytl="10" xbr="80" ybr="60"/><polygon label="smoke" points="10,10;40,10;20,30"/><points label="ignored" points="1,1"/></image></annotations>"""
    result = parse_annotation_overlay(content, "annotations.xml", "frame.jpg")
    assert result["format"] == "CVAT Images"
    assert [item["label"] for item in result["items"]] == ["person", "smoke"]
    assert result["ignored_shapes"] == 1
    metadata = annotation_document_metadata(content, "annotations.xml")
    assert metadata["image_refs"] == ["images/frame.jpg"]
    assert metadata["shape_stats"] == {"boxes": 1, "polygons": 1, "ignored": 1}


def test_parse_coco_polygon_without_bbox():
    content = json.dumps(
        {
            "images": [{"id": 1, "file_name": "frame.jpg", "width": 100, "height": 100}],
            "categories": [{"id": 1, "name": "smoke"}],
            "annotations": [
                {
                    "id": 1,
                    "image_id": 1,
                    "category_id": 1,
                    "segmentation": [[10, 10, 40, 10, 20, 30]],
                }
            ],
        }
    ).encode()
    result = parse_coco_overlay(content, "frame.jpg")
    assert result["items"][0]["label"] == "smoke"
    assert result["items"][0]["bbox"] == pytest.approx(
        {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.2}
    )


def test_metadata_does_not_link_images_without_supported_annotations():
    coco = json.dumps(
        {
            "images": [{"id": 1, "file_name": "empty.jpg"}],
            "categories": [],
            "annotations": [],
        }
    ).encode()
    cvat = b'<annotations><image id="0" name="empty.jpg" width="10" height="10"/></annotations>'
    voc = b"<annotation><filename>empty.jpg</filename><size><width>10</width><height>10</height></size></annotation>"
    assert annotation_document_metadata(coco, "instances.json")["image_refs"] == []
    assert annotation_document_metadata(cvat, "annotations.xml")["image_refs"] == []
    assert annotation_document_metadata(voc, "empty.xml")["image_refs"] == []
