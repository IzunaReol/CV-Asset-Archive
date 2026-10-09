from typing import Any, Literal

from .schemas import Role

MenuPermission = Literal[
    "library", "datasets", "relations", "lineage", "downloads", "trash",
    "tags", "formats", "admin", "logs",
]
ActionPermission = Literal[
    "asset_upload", "asset_edit", "asset_delete", "saved_view_manage",
    "dataset_create_edit", "dataset_members_manage", "dataset_version_publish",
    "dataset_version_restore", "dataset_delete", "dataset_model_manage", "dataset_manage",
    "relation_manage", "relation_revoke", "export_create", "trash_manage",
    "tag_manage", "format_manage", "user_manage",
]

MENU_DEFINITIONS = [
    {"key": "library", "name": "素材库"}, {"key": "datasets", "name": "数据集"},
    {"key": "relations", "name": "关联关系"}, {"key": "lineage", "name": "模型溯源"},
    {"key": "downloads", "name": "任务中心"}, {"key": "trash", "name": "回收站"},
    {"key": "tags", "name": "标签管理"}, {"key": "formats", "name": "格式管理"},
    {"key": "admin", "name": "用户管理"}, {"key": "logs", "name": "系统日志"},
]
ACTION_DEFINITIONS = [
    {"key": "asset_upload", "name": "上传素材", "menu": "library"},
    {"key": "asset_edit", "name": "编辑素材", "menu": "library"},
    {"key": "asset_delete", "name": "删除素材", "menu": "library"},
    {"key": "saved_view_manage", "name": "管理保存视图", "menu": "library"},
    {"key": "dataset_create_edit", "name": "创建与编辑数据集", "menu": "datasets"},
    {"key": "dataset_members_manage", "name": "管理数据集成员", "menu": "datasets"},
    {"key": "dataset_version_publish", "name": "发布数据集版本", "menu": "datasets"},
    {"key": "dataset_version_restore", "name": "恢复数据集版本", "menu": "datasets"},
    {"key": "dataset_delete", "name": "删除数据集", "menu": "datasets"},
    {"key": "dataset_model_manage", "name": "管理数据集模型关联", "menu": "datasets"},
    {"key": "relation_manage", "name": "建立关联关系", "menu": "relations"},
    {"key": "relation_revoke", "name": "撤销关联关系", "menu": "relations"},
    {"key": "export_create", "name": "创建导出任务", "menu": "downloads"},
    {"key": "trash_manage", "name": "管理回收站", "menu": "trash"},
    {"key": "tag_manage", "name": "管理标签", "menu": "tags"},
    {"key": "format_manage", "name": "管理格式", "menu": "formats"},
    {"key": "user_manage", "name": "管理用户", "menu": "admin"},
]
ACTION_MENU = {item["key"]: item["menu"] for item in ACTION_DEFINITIONS}
ALL_MENU_PERMISSIONS = [item["key"] for item in MENU_DEFINITIONS]
ALL_ACTION_PERMISSIONS = [item["key"] for item in ACTION_DEFINITIONS]

ROLE_MENU_PERMISSIONS = {
    Role.ADMIN.value: ALL_MENU_PERMISSIONS,
    Role.DATA_MANAGER.value: ["library", "datasets", "relations", "lineage", "downloads", "trash"],
    Role.ANNOTATOR.value: ["library", "datasets", "relations", "downloads"],
    Role.ML_ENGINEER.value: ["library", "datasets", "relations", "lineage", "downloads"],
    Role.VIEWER.value: ["library", "datasets", "relations", "lineage", "downloads"],
    Role.CUSTOM.value: [],
}
ROLE_ACTION_PERMISSIONS = {
    Role.ADMIN.value: ALL_ACTION_PERMISSIONS,
    Role.DATA_MANAGER.value: ["asset_upload", "asset_edit", "asset_delete", "saved_view_manage", "dataset_create_edit", "dataset_members_manage", "dataset_version_publish", "dataset_version_restore", "dataset_delete", "dataset_model_manage", "relation_manage", "relation_revoke", "export_create", "trash_manage"],
    Role.ANNOTATOR.value: ["asset_upload", "asset_edit", "saved_view_manage", "dataset_create_edit", "dataset_members_manage", "dataset_version_publish", "relation_manage", "export_create"],
    Role.ML_ENGINEER.value: ["asset_upload", "asset_edit", "saved_view_manage", "dataset_create_edit", "dataset_members_manage", "dataset_version_publish", "dataset_model_manage", "relation_manage", "export_create"],
    Role.VIEWER.value: ["saved_view_manage"],
    Role.CUSTOM.value: [],
}


def effective_menu_permissions(user: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for role in user.get("roles", []):
        values.update(user.get("menu_permissions", []) if role == Role.CUSTOM.value else ROLE_MENU_PERMISSIONS.get(role, []))
    return values


def effective_action_permissions(user: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for role in user.get("roles", []):
        role_values = user.get("action_permissions", []) if role == Role.CUSTOM.value else ROLE_ACTION_PERMISSIONS.get(role, [])
        values.update(role_values)
        if "dataset_manage" in role_values:
            values.update({
                "dataset_create_edit", "dataset_members_manage", "dataset_version_publish",
                "dataset_version_restore", "dataset_delete", "dataset_model_manage",
            })
    return values
