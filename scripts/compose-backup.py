"""Back up or restore a Docker Compose deployment without shell redirection.

Restore requires a fresh Compose project so existing volumes are never erased.
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "docker-compose.yml"


def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=capture, cwd=ROOT)
    return result.stdout.strip() if capture else ""


def compose(project: str, *args: str, capture: bool = False) -> str:
    return run("docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), *args, capture=capture)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def file_manifest(directory: Path) -> dict[str, str]:
    return {file.relative_to(directory).as_posix(): digest(file)
            for file in sorted(directory.rglob("*"))
            if file.is_file() and file != directory / "manifest.json"}


def stream_command(destination: Path, command: list[str]) -> None:
    with destination.open("wb") as output:
        subprocess.run(command, stdout=output, check=True, cwd=ROOT)


def backup(project: str, destination: Path) -> None:
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("备份目录已存在，请使用新目录")
    if ROOT == destination or ROOT in destination.parents:
        raise ValueError("备份必须保存在仓库外")
    running = set(compose(project, "ps", "--status", "running", "--services", capture=True).splitlines())
    if not {"mongodb", "minio"}.issubset(running):
        raise ValueError("MongoDB 和 MinIO 必须处于运行状态")
    destination.mkdir(parents=True)
    stopped = sorted(running & {"api", "worker"})
    try:
        if stopped:
            compose(project, "stop", *stopped)
        archive = destination / "mongo.archive.gz"
        command = ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE),
                   "exec", "-T", "mongodb", "mongodump", "--archive", "--gzip"]
        stream_command(archive, command)
        minio_dir = destination / "minio"
        minio_dir.mkdir()
        container = compose(project, "ps", "-q", "minio", capture=True)
        if not container:
            raise RuntimeError("找不到 MinIO 容器")
        run("docker", "cp", f"{container}:/data/.", str(minio_dir))
        manifest = {"project": project, "created_at": datetime.now(UTC).isoformat(),
                    "files": file_manifest(destination)}
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"备份完成：{destination}（{len(manifest['files'])} 个文件）")
    finally:
        if stopped:
            compose(project, "up", "-d", *stopped)


def restore(project: str, source: Path, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("恢复需要 --confirm-new-project，且目标必须是全新的 Compose 项目")
    source = source.resolve()
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("备份清单不存在")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("files", {})
    if not expected or expected != file_manifest(source):
        raise ValueError("备份文件缺失、增加或校验值不一致")
    config = json.loads(compose(project, "config", "--format", "json", capture=True))
    volume_names = {item["name"] for item in config["volumes"].values()}
    for volume in volume_names:
        exists = subprocess.run(["docker", "volume", "inspect", volume],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if exists.returncode == 0:
            raise ValueError(f"目标卷已存在：{volume}；请使用新的项目名，避免覆盖现有数据")
    compose(project, "up", "-d", "mongodb", "redis", "minio")
    container = compose(project, "ps", "-q", "minio", capture=True)
    compose(project, "stop", "minio")
    run("docker", "cp", str(source / "minio") + "/.", f"{container}:/data/")
    command = ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE),
               "exec", "-T", "mongodb", "mongorestore", "--drop", "--archive", "--gzip"]
    with (source / "mongo.archive.gz").open("rb") as archive:
        subprocess.run(command, stdin=archive, check=True, cwd=ROOT)
    compose(project, "up", "-d", "minio", "api", "worker", "frontend")
    print(f"已恢复到新项目 {project}；请检查健康状态并抽查素材、关系和导出")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    back = subcommands.add_parser("backup", help="备份现有 Compose 项目")
    back.add_argument("destination", type=Path)
    back.add_argument("--project", default="cv-archive")
    recovering = subcommands.add_parser("restore", help="恢复到全新的 Compose 项目")
    recovering.add_argument("source", type=Path)
    recovering.add_argument("--project", required=True)
    recovering.add_argument("--confirm-new-project", action="store_true")
    args = parser.parse_args()
    if args.action == "backup":
        backup(args.project, args.destination)
    else:
        restore(args.project, args.source, args.confirm_new_project)


if __name__ == "__main__":
    main()
