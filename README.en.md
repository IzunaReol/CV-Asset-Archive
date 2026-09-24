# CV Asset Archive

English | [简体中文](README.md)

CV Asset Archive is an asset and relationship management system for computer vision teams. It stores images, videos, annotations, models, and archives in one place, with search, annotation preview, lineage tracking, recycle-bin recovery, and asynchronous exports.

## Features

- Batch upload for images, videos, annotations, models, and archives
- Automatic format detection with a configurable 10 GB default per-file limit
- Image thumbnails, video posters, in-browser playback, and original-resolution preview
- Fuzzy search over names and notes, advanced filters, saved views, and multi-value tags
- Import for YOLO Detection, Pascal VOC, CVAT for images, and COCO annotation packages
- Bounding-box and polygon overlays
- Automatic image-to-annotation matching, model-to-dataset-version relationships, history, and model lineage
- Soft deletion, recycle-bin recovery, and background physical cleanup
- Unified job center with type, state, and creation-time filters, retry, export cancellation, heartbeats, and expiring downloads
- Chunked uploads for files 64 MB and larger, with pause, resume, and session recovery after reselecting the same file
- User, role, tag, format, and audit management, with deletion protection for built-in tags
- Dataset membership, immutable versions, custom version names, comparison, and restoration
- Dataset duplication, version-specific model relationships, and dataset exports
- Light and dark themes

## Technology

| Component | Technology |
| --- | --- |
| Frontend | Vue 3, TypeScript, Vite |
| API | Python 3.12, FastAPI, Pydantic, PyMongo Async |
| Metadata | MongoDB |
| Object storage | MinIO |
| Background jobs | Celery, Redis |
| Media processing | Pillow, FFmpeg |
| Deployment | Native Windows environment or Linux Docker Compose |

See the [system design](docs/system-design.md), [API conventions](docs/api-conventions.md), [relationship revocation](docs/relation-revoke.md), and [operations guide](docs/operations.md) for details.

## Native Windows Setup

Requirements: Windows 11, Python 3.12+, Node.js 20+, and curl. Dependencies, data, and logs are kept under `.runtime` in the project directory. No Windows service is installed.

Install once:

```powershell
.\install-native.cmd
```

If direct downloads fail, the installer tries `http://127.0.0.1:7890`. A different proxy can be supplied explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-native.ps1 -FallbackProxy http://127.0.0.1:7890
```

Start and stop:

```powershell
.\start-native.cmd
.\stop-native.cmd
```

Open `http://localhost:5173` after startup. The initial username and password are both `admin`. Logs are stored in `.runtime/logs` and data in `.runtime/data`.

## Docker Compose Deployment

Linux with Docker Compose is recommended for server deployment. Copy the environment template and replace every default credential:

```bash
cp .env.example .env
docker compose -f deploy/docker-compose.yml up --build -d
```

Default endpoints:

- Web: `http://localhost:8080`
- API documentation: `http://localhost:8000/docs`
- Readiness check: `http://localhost:8000/health/ready`
- MinIO console: `http://localhost:9001`

See the [deployment guide](deploy/README.md) for PowerShell scripts and offline image import/export.

## Configuration

Common settings are documented in [.env.example](.env.example):

| Variable | Purpose | Default example |
| --- | --- | --- |
| `JWT_SECRET` | Access-token signing secret | Must be replaced |
| `INITIAL_ADMIN_USERNAME` | Initial administrator | `admin` |
| `INITIAL_ADMIN_PASSWORD` | Initial administrator password | `admin` |
| `MAX_UPLOAD_SIZE_BYTES` | Per-file upload limit | `10737418240` |
| `EXPORT_EXPIRY_HOURS` | Export lifetime in hours | `72` |
| `MINIO_*` | Object-storage connection | Example values |
| `MONGODB_*` | MongoDB connection | Example values |
| `REDIS_URL` | Celery queue connection | Example value |

Change the administrator password, MinIO credentials, and JWT secret before a team deployment.

## Development and Tests

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker scripts
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

The isolated API workflow test is available at `scripts/runtime-e2e.py`. See the [testing guide](docs/testing.md) and [v1.3.0 release checklist](docs/release-checklist.md) for the full scope.

## Preparing to upgrade to v1.3.0

Back up MongoDB, MinIO, and deployment configuration before upgrading from v1.2.1. Update the source and dependencies, rebuild the frontend, and verify the job center, worker heartbeats, upload pause and resume, built-in tag protection, and the migration reconciliation report. The model relationship schema is unchanged; upgrades from older versions should still follow the [v1.2.0 migration notes](docs/releases/v1.2.0.md). A rollback requires the pre-upgrade database backup, not just older code.

See the [dataset guide](docs/datasets.md) and [v1.3.0 release notes](docs/releases/v1.3.0.md) for behavior, validation status, and known limitations.

## Documentation

- [System design](docs/system-design.md)
- [API conventions](docs/api-conventions.md)
- [Deployment guide](deploy/README.md)
- [Operations guide](docs/operations.md)
- [Testing guide](docs/testing.md)
- [Roadmap](docs/roadmap.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Repository Policy

Do not commit production assets, model weights, databases, runtime logs, credentials, or personal information. Original planning documents and internal implementation proposals are kept outside Git history. See [project governance](docs/project-governance.md) for details.

## License

Licensed under the [Apache License 2.0](LICENSE).
