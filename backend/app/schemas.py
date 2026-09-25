from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Role(StrEnum):
    ADMIN = "admin"
    DATA_MANAGER = "data_manager"
    ANNOTATOR = "annotator"
    ML_ENGINEER = "ml_engineer"
    VIEWER = "viewer"


class AssetType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    ANNOTATION = "annotation"
    MODEL = "model"
    ARCHIVE = "archive"
    IMAGE_ANNOTATION = "image_annotation"
    OTHER = "other"


class RelationType(StrEnum):
    ANNOTATES = "annotates"
    CONTAINS = "contains"
    TRAINED_ON = "trained_on"
    PRODUCED_BY = "produced_by"
    VERSION_OF = "version_of"


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    access_expires_at: datetime
    user: dict[str, Any]


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    mime_type: str = Field(min_length=1, max_length=150)
    asset_type: AssetType
    project: str = Field(default="未分类", min_length=1, max_length=100)
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class UploadCompleteRequest(BaseModel):
    upload_session_id: str
    tags: dict[str, str | list[str]] = Field(default_factory=dict)


class UploadBatchInitRequest(BaseModel):
    files: list[UploadInitRequest] = Field(min_length=1, max_length=100)


class UploadBatchCompleteRequest(BaseModel):
    upload_session_ids: list[str] = Field(min_length=1, max_length=100)
    tags: dict[str, str | list[str]] = Field(default_factory=dict)

    @field_validator("upload_session_ids")
    @classmethod
    def unique_session_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("上传会话不能重复")
        return value


class BatchTagRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=1000)
    selection_id: str | None = None
    excluded_ids: list[str] = Field(default_factory=list, max_length=5000)
    set_tags: dict[str, str | list[str]] = Field(default_factory=dict)
    remove_tags: list[str] = Field(default_factory=list)
    remove_tag_values: dict[str, list[str]] = Field(default_factory=dict)


class AssetRemarkUpdate(BaseModel):
    remark: str = Field(default="", max_length=1000)


class BatchAssetDeleteRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=5000)
    selection_id: str | None = None
    excluded_ids: list[str] = Field(default_factory=list, max_length=5000)


class AssetSelectionCreate(BaseModel):
    q: str = Field(default="", max_length=200)
    no_tags: bool = False
    asset_type: list[AssetType] = Field(default_factory=list)
    match: Literal["all", "any"] = "all"
    tag: list[str] = Field(default_factory=list, max_length=30)


class RelationCreate(BaseModel):
    source_id: str
    target_id: str
    relation_type: RelationType
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_id")
    @classmethod
    def distinct_target(cls, value: str, info: Any) -> str:
        if value == info.data.get("source_id"):
            raise ValueError("source and target must differ")
        return value


class RelationBatchRequest(BaseModel):
    relations: list[RelationCreate] = Field(min_length=1, max_length=5000)


class AnnotationMatchPreviewRequest(BaseModel):
    image_ids: list[str] = Field(default_factory=list, max_length=5000)
    annotation_ids: list[str] = Field(default_factory=list, max_length=5000)


class RevokeRelationRequest(BaseModel):
    reason: str = ""
    replacement_relation_id: str | None = None


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    asset_ids: list[str] = Field(default_factory=list, max_length=100000)
    selection_id: str | None = None
    excluded_ids: list[str] = Field(default_factory=list, max_length=5000)
    freeze: bool = False


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    remark: str = Field(default="", max_length=1000)
    status: str = Field(default="待整理", min_length=1, max_length=50)


class DatasetUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    remark: str = Field(default="", max_length=1000)
    status: str = Field(min_length=1, max_length=50)


class DatasetMembersRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=100000)


class DatasetPublishRequest(BaseModel):
    version: str = Field(pattern=r"^v?[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
    release_note: str = Field(default="", max_length=2000)


class DatasetRestoreRequest(BaseModel):
    version_id: str


class DatasetExportRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class DatasetModelLinkRequest(BaseModel):
    model_id: str
    version_id: str
    remark: str = Field(default="", max_length=1000)


class SavedViewCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    query: dict[str, Any]
    sort: list[dict[str, Literal["asc", "desc"]]] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    shared: bool = False


class SavedViewUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_ids: list[str] = Field(default_factory=list, max_length=100000)
    selection_id: str | None = None
    excluded_ids: list[str] = Field(default_factory=list, max_length=5000)
    name: str = Field(min_length=1, max_length=120)


class TagDefinitionCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=50)
    values: list[str] = Field(default_factory=list)
    color: str = Field(default="#64748b", pattern=r"^#[0-9a-fA-F]{6}$")
    asset_types: list[AssetType] = Field(default_factory=list)
    free_input: bool = False


class TagDefinitionUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    values: list[str] = Field(default_factory=list)
    color: str = Field(default="#64748b", pattern=r"^#[0-9a-fA-F]{6}$")
    asset_types: list[AssetType] = Field(default_factory=list)
    free_input: bool = False
