import asyncio

from .config import get_settings
from .database import db, ensure_indexes
from .migrations import run_migrations
from .schemas import Role
from .security import hash_password
from .storage import ensure_bucket
from .utils import new_id, now

settings = get_settings()

DEFAULT_TAGS = [
    ("status", "状态", ["待整理", "未标注", "已标注", "审核中", "待复核", "已训练"], "#d95c35"),
    ("project", "项目", [], "#2764c6"),
    ("algorithm", "所属算法", [], "#7c3aed"),
    ("scene", "场景", ["室内", "室外", "夜间", "车内"], "#0891b2"),
    ("lighting", "光照", ["强", "中", "弱"], "#ca8a04"),
    ("annotation_format", "标注格式", ["COCO", "YOLO", "VOC"], "#16a34a"),
    ("model_framework", "模型框架", ["YOLO11", "YOLOv8", "RT-DETR"], "#475569"),
    ("model_version", "模型版本", [], "#64748b"),
]

DEFAULT_FORMATS = {
    "image": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".avif"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpeg", ".mpg", ".ts", ".mts", ".m2ts"],
    "annotation": [".txt", ".xml", ".json", ".yaml", ".yml", ".csv"],
    "model": [".pt", ".pth", ".onnx", ".engine", ".weights", ".ckpt", ".pb", ".tflite", ".torchscript", ".safetensors", ".mlmodel", ".bin"],
    "archive": [".rar", ".zip", ".7z"],
    "image_annotation": [".rar", ".zip", ".7z"],
}

DEFAULT_METRICS = [
    ("accuracy", "准确率 (Accuracy)", "图像分类", "分类正确的样本比例"),
    ("precision", "精确率 (Precision)", "图像分类", "正确识别为正类的样本比例"),
    ("recall", "召回率 (Recall)", "图像分类", "实际为正类的样本中被正确识别的比例"),
    ("f1", "F1分数 (F1 Score)", "图像分类", "精确率和召回率的调和平均值"),
    ("map", "mAP (mean Average Precision)", "目标检测", "各类别平均精度的均值，用于衡量目标检测模型的整体性能"),
    ("iou", "IoU (Intersection over Union)", "目标检测", "预测框与真实框的交并比"),
    ("ap", "AP (Average Precision)", "目标检测", "基于不同置信度阈值形成的精确率－召回率曲线计算的平均精度"),
    ("pixel_accuracy", "Pixel Accuracy", "语义分割", "正确分类的像素比例"),
    ("miou", "Mean Intersection over Union (mIoU)", "语义分割", "所有类别交并比的平均值"),
    ("dice", "Dice Coefficient", "语义分割", "衡量预测与真实标签的重合程度"),
    ("instance_map", "mAP (mean Average Precision)", "实例分割", "与目标检测类似，但针对实例级别的预测"),
    ("instance_iou", "IoU (Intersection over Union)", "实例分割", "实例级别的交并比"),
    ("cer", "CER (Character Error Rate)", "OCR", "字符错误率，衡量OCR模型的字符识别准确率"),
    ("wer", "WER (Word Error Rate)", "OCR", "单词错误率，衡量OCR模型的单词识别准确率"),
    ("pck", "PCK (Percentage of Correct Keypoints)", "姿态和关键点", "关键点正确率，衡量姿态估计模型的准确性"),
    ("oks", "OKS (Object Keypoint Similarity)", "姿态和关键点", "对象关键点相似度，用于姿态估计任务"),
]

DEFAULT_METRIC_CATEGORIES = ["图像分类", "目标检测", "语义分割", "实例分割", "OCR", "姿态和关键点"]


async def ensure_default_metric_categories() -> None:
    for order, name in enumerate(DEFAULT_METRIC_CATEGORIES):
        await db.metric_categories.update_one(
            {"name": name},
            {"$setOnInsert": {
                "id": f"metric-category-{order}", "name": name,
                "order": order, "built_in": True,
                "created_at": now(), "updated_at": now(),
            }},
            upsert=True,
        )


async def ensure_default_metrics() -> None:
    for key, name, category, description in DEFAULT_METRICS:
        await db.metric_definitions.update_one(
            {"id": f"metric-{key}"},
            {"$setOnInsert": {
                "id": f"metric-{key}", "name": name, "category": category,
                "description": description, "built_in": True,
                "created_at": now(), "updated_at": now(),
            }},
            upsert=True,
        )


async def bootstrap() -> None:
    await run_migrations()
    await ensure_indexes()
    if await db.users.count_documents({}) == 0:
        await db.users.insert_one(
            {
                "id": new_id(),
                "username": settings.initial_admin_username,
                "password_hash": hash_password(settings.initial_admin_password),
                "roles": [Role.ADMIN.value],
                "status": "active",
                "must_change_password": False,
                "created_at": now(),
                "updated_at": now(),
            }
        )
    for key, name, values, color in DEFAULT_TAGS:
        await db.tag_definitions.update_one(
            {"key": key},
            {
                "$set": {"built_in": True},
                "$setOnInsert": {
                    "id": new_id(),
                    "key": key,
                    "name": name,
                    "values": values,
                    "color": color,
                    "asset_types": [],
                    "free_input": not bool(values),
                    "created_at": now(),
                }
            },
            upsert=True,
        )
    for asset_type, extensions in DEFAULT_FORMATS.items():
        await db.format_definitions.update_one(
            {"asset_type": asset_type},
            {"$set": {"built_in": True, "protected_extensions": extensions}, "$setOnInsert": {"id": new_id(), "asset_type": asset_type, "remark": "", "extensions": extensions, "created_at": now(), "updated_at": now()}},
            upsert=True,
        )
    await ensure_default_metric_categories()
    await ensure_default_metrics()
    await db.format_definitions.delete_one({"asset_type": "other"})
    await asyncio.to_thread(ensure_bucket)
