import json
import zipfile

import pytest
from worker.tasks import (
    annotation_metadata,
    cvat_yolo_pairs,
    download_object,
    fail_asset,
    failure_details,
    inspect_supported_bundle,
    sha256_file,
    sha256_object,
    yolo_archive_class_names,
    yolo_class_names,
)


def test_sha256_file(tmp_path):
    path = tmp_path / "sample.bin"
    path.write_bytes(b"cv-archive")
    assert sha256_file(path) == "d7751e53e4aa029c2cd138f07a3c3d4492df11dba3d4e761fd8cfb1ee195396d"


def test_sha256_object_streams_without_a_temporary_file(monkeypatch):
    calls = []

    class Response:
        def __init__(self):
            self.chunks = iter((b"cv-", b"archive", b""))

        def read(self, _size):
            return next(self.chunks)

        def close(self):
            calls.append("close")

        def release_conn(self):
            calls.append("release")

    class Storage:
        def get_object(self, bucket, object_key):
            calls.append((bucket, object_key))
            return Response()

    monkeypatch.setattr("worker.tasks.storage", Storage())
    assert sha256_object("models/sample.pt") == (
        "d7751e53e4aa029c2cd138f07a3c3d4492df11dba3d4e761fd8cfb1ee195396d"
    )
    assert calls == [("cv-assets", "models/sample.pt"), "close", "release"]


def test_download_object_writes_final_path_without_minio_part_file(tmp_path, monkeypatch):
    calls = []

    class Response:
        def __init__(self):
            self.chunks = iter((b"image-", b"bytes", b""))

        def read(self, _size):
            return next(self.chunks)

        def close(self):
            calls.append("close")

        def release_conn(self):
            calls.append("release")

    class Storage:
        def get_object(self, bucket, object_key):
            calls.append((bucket, object_key))
            return Response()

    monkeypatch.setattr("worker.tasks.storage", Storage())
    target = tmp_path / "sample.jpg"
    download_object("images/sample.jpg", target)
    assert target.read_bytes() == b"image-bytes"
    assert not list(tmp_path.glob("*.part.minio"))
    assert calls == [("cv-assets", "images/sample.jpg"), "close", "release"]


def test_parse_coco(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps({"images": [{"id": 1}], "annotations": [{"id": 2}], "categories": []}),
        encoding="utf-8",
    )
    metadata = annotation_metadata(path)
    assert metadata["annotation_format"] == "COCO"
    assert metadata["image_count"] == 1
    assert metadata["annotation_count"] == 1
    assert metadata["shape_stats"]["ignored"] == 1


def test_recognize_common_annotation_files_without_rejecting_archive(tmp_path):
    xml_path = tmp_path / "annotations.xml"
    xml_path.write_text("<annotations />", encoding="utf-8")
    txt_path = tmp_path / "labels.txt"
    txt_path.write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    assert annotation_metadata(xml_path)["annotation_format"] == "XML / CVAT / VOC"
    assert annotation_metadata(txt_path)["annotation_format"] == "TXT / YOLO"


def test_parse_yolo_and_reject_invalid_rows(tmp_path):
    valid = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("labels/a.txt", "0 0.5 0.5 0.2 0.2\n")
    assert annotation_metadata(valid)["label_file_count"] == 1

    invalid = tmp_path / "invalid.zip"
    with zipfile.ZipFile(invalid, "w") as archive:
        archive.writestr("labels/a.txt", "0 1.2 0.5 0.2 0.2\n")
    with pytest.raises(ValueError, match="invalid label rows"):
        annotation_metadata(invalid)


def test_detect_cvat_yolo_image_label_pairs(tmp_path):
    package = tmp_path / "cvat.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("Validation.txt", "images/Validation/a.jpg\n")
        archive.writestr("images/Validation/a.jpg", b"image")
        archive.writestr("labels/Validation/a.txt", "0 0.5 0.5 0.2 0.2\n")
        archive.writestr("labels/Validation/unmatched.txt", "0 0.5 0.5 0.2 0.2\n")
    assert cvat_yolo_pairs(package) == [("images/Validation/a.jpg", "labels/Validation/a.txt")]


def test_yolo_class_names_support_inline_yaml_and_cvat_obj_names(tmp_path):
    assert yolo_class_names(b"names: ['smoking', 'phone']\n") == ["smoking", "phone"]
    package = tmp_path / "classes.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("obj.names", "smoking\nphone\n")
    with zipfile.ZipFile(package) as archive:
        assert yolo_archive_class_names(archive) == ["smoking", "phone"]


def test_plain_archive_is_not_a_cvat_import_candidate(tmp_path):
    package = tmp_path / "files.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("documents/readme.txt", "ordinary archive")
    assert cvat_yolo_pairs(package) == []


@pytest.mark.parametrize(
    ("document_name", "document", "expected"),
    [
        (
            "Annotations/a.xml",
            "<annotation><filename>a.jpg</filename><size><width>10</width><height>10</height></size></annotation>",
            "Pascal VOC",
        ),
        (
            "annotations.xml",
            '<annotations><image id="0" name="a.jpg" width="10" height="10"/></annotations>',
            "CVAT Images",
        ),
        (
            "annotations/instances.json",
            '{"images":[{"id":1,"file_name":"a.jpg","width":10,"height":10}],"annotations":[],"categories":[]}',
            "COCO",
        ),
    ],
)
def test_detect_supported_xml_and_coco_packages(tmp_path, document_name, document, expected):
    package = tmp_path / f"{expected}.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("images/a.jpg", b"image")
        archive.writestr(document_name, document)
    manifest = inspect_supported_bundle(package)
    assert manifest["detected"] is True
    assert manifest["format"] == expected


def test_reject_package_with_multiple_annotation_formats(tmp_path):
    package = tmp_path / "mixed.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("images/a.jpg", b"image")
        archive.writestr(
            "Annotations/a.xml",
            "<annotation><filename>a.jpg</filename><size><width>10</width><height>10</height></size></annotation>",
        )
        archive.writestr(
            "annotations/instances.json",
            '{"images":[{"id":1,"file_name":"a.jpg"}],"annotations":[],"categories":[]}',
        )
    with pytest.raises(ValueError, match="压缩包包含多种标注格式，请分别上传"):
        inspect_supported_bundle(package)


def test_permission_failure_has_readable_status():
    assert failure_details(PermissionError("denied")) == {
        "code": "PROCESS_PERMISSION_DENIED",
        "message": "处理目录没有读写权限",
    }


def test_asset_status_changes_to_failed_when_processing_stops(monkeypatch):
    updates = []

    class Assets:
        def update_one(self, query, update):
            updates.append((query, update))

    class Database:
        assets = Assets()

    monkeypatch.setattr("worker.tasks.database", Database())
    fail_asset("asset-1", PermissionError("denied"))
    assert updates[0][0] == {"id": "asset-1"}
    assert updates[0][1]["$set"]["status"] == "failed"
    assert updates[0][1]["$set"]["processing_error"]["code"] == "PROCESS_PERMISSION_DENIED"
