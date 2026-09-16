import pytest
from pydantic import ValidationError

from app.schemas import (
    AnnotationMatchPreviewRequest,
    AssetType,
    DatasetCreate,
    DatasetMembersRequest,
    DatasetModelLinkRequest,
    DatasetPublishRequest,
    RelationCreate,
    RevokeRelationRequest,
    SavedViewUpdate,
    TagDefinitionCreate,
    TagDefinitionUpdate,
    UploadInitRequest,
)
from app.utils import public_document
from app.routers.relations import filename_stem, relation_type_error


def test_private_database_fields_are_removed():
    result = public_document(
        {"id": "u1", "password_hash": "secret", "token_hash": "token", "_id": "mongo"}
    )
    assert result == {"id": "u1"}


def test_upload_rejects_empty_files():
    with pytest.raises(ValidationError):
        UploadInitRequest(
            filename="empty.jpg",
            size=0,
            mime_type="image/jpeg",
            asset_type="image",
            project="demo",
        )


def test_archive_upload_types_are_supported():
    assert AssetType("archive") is AssetType.ARCHIVE
    assert AssetType("image_annotation") is AssetType.IMAGE_ANNOTATION


def test_relation_revoke_reason_is_optional_and_unlimited():
    assert RevokeRelationRequest().reason == ""
    assert len(RevokeRelationRequest(reason="原因" * 1000).reason) == 2000


def test_relation_rejects_self_reference():
    with pytest.raises(ValidationError):
        RelationCreate(source_id="same", target_id="same", relation_type="contains")


def test_annotation_match_stem_ignores_extension_case():
    assert filename_stem("001.JPG") == filename_stem("001.txt") == "001"


def test_annotation_match_preview_allows_full_library_scan():
    request = AnnotationMatchPreviewRequest()
    assert request.image_ids == []
    assert request.annotation_ids == []


def test_relation_type_direction_is_validated():
    assert relation_type_error({"type": "annotation"}, {"type": "image"}, "annotates") is None
    assert relation_type_error({"type": "image"}, {"type": "annotation"}, "annotates") == (
        "RELATION_TYPE_MISMATCH",
        "对应标注关系必须由标注指向图片",
    )
    assert relation_type_error({"type": "model"}, {"kind": "snapshot"}, "trained_on") is None


def test_tag_key_is_storage_safe():
    with pytest.raises(ValidationError):
        TagDefinitionCreate(key="bad.key", name="错误字段")


def test_saved_view_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        SavedViewUpdate(name="")


def test_tag_update_rejects_invalid_color():
    with pytest.raises(ValidationError):
        TagDefinitionUpdate(name="光照", color="yellow")


def test_dataset_contracts_support_snapshot_workflow():
    dataset = DatasetCreate(name="训练集", status="待整理")
    assert dataset.remark == ""
    assert DatasetMembersRequest(asset_ids=["a1", "a2"]).asset_ids == ["a1", "a2"]
    assert DatasetPublishRequest(version="v1.1").release_note == ""


def test_dataset_members_cannot_be_empty():
    with pytest.raises(ValidationError):
        DatasetMembersRequest(asset_ids=[])


def test_model_can_target_dataset_version():
    assert relation_type_error(
        {"type": "model"}, {"kind": "dataset_version"}, "trained_on"
    ) is None


def test_dataset_model_link_accepts_version_and_remark():
    link = DatasetModelLinkRequest(model_id="model-1", version_id="version-1", remark="初次训练")
    assert link.model_id == "model-1"
    assert link.version_id == "version-1"
    assert link.remark == "初次训练"
