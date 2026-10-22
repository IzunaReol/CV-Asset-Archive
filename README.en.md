# CV Asset Archive

English | [简体中文](README.md)

Current version: **v2.0.0**. See the [release notes](docs/releases/v2.0.0.md) and [release checklist](docs/release-checklist.md) for changes and remaining validation limits.

CV Asset Archive is an asset and relationship management system for computer vision teams. It stores images, videos, annotations, models, and archives in one place, with search, annotation preview, lineage tracking, recycle-bin recovery, and asynchronous exports.

## Features

- Project overview with multi-project selection, current dataset composition, deduplicated models, and tagged files
- Required dataset project membership and per-model parameter metadata shared across asset details and dataset model management
- Six built-in metric categories and 16 definitions, with custom category and metric management
- Usage-impact preview before deletion or overwrite; deleting referenced assets requires a second confirmation and clears their associations

- Batch upload for images, videos, annotations, models, and archives
- Same-name checks before upload, grouped by asset type, with overwrite or automatic rename choices
- Automatic format detection with a configurable 10 GB default per-file limit
- Image thumbnails, video posters, in-browser playback, and original-resolution preview
- Fuzzy search over names and notes, advanced filters, saved views, and multi-value tags
- Import for YOLO Detection, Pascal VOC, CVAT for images, and COCO annotation packages
- Bounding-box and polygon overlays
- Automatic image-to-annotation matching, model-to-dataset-version relationships, history, and model lineage
- Soft deletion, recycle-bin recovery, and background physical cleanup
- Unified job center with type, state, and creation-time filters, retry, export cancellation, heartbeats, and expiring downloads
- Chunked uploads for files 64 MB and larger, with pause, resume, and session recovery after reselecting the same file
- Fixed and custom roles with separate menu-access and operation permissions enforced by both the UI and backend APIs
- Tag, format, and audit management, with deletion protection for built-in tags
- Dataset membership, version snapshots, custom version names, comparison, and restoration; explicitly confirmed asset deletion can remove historical version members, and recycle-bin recovery does not restore associations
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

Requirements: Windows 11, Python 3.12+, Node.js 22.20+, and curl. Dependencies, data, and logs are kept under `.runtime` in the project directory. No Windows service is installed.

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

Docker Compose v2 is required. The first deployment creates `.env` and generates random JWT, administrator, and MinIO credentials.

On Windows, double-click or run:

```powershell
.\deploy-windows.cmd
```

On Linux, run:

```bash
bash deploy-linux.sh
```

For routine startup after deployment:

```powershell
.\start-windows.cmd
```

```bash
bash start-linux.sh
```

Default endpoints:

- Web: `http://localhost:8080` (change `FRONTEND_PORT` in `.env` when the port is occupied)
- API documentation: `http://localhost:8000/docs`
- Readiness check: `http://localhost:8000/health/ready`
- MinIO console: `http://localhost:9001`

See the [deployment guide](deploy/README.md) for script options, stopping services, and offline image import/export.

## Configuration

Common settings are documented in [.env.example](.env.example):

| Variable | Purpose | Default example |
| --- | --- | --- |
| `JWT_SECRET` | Access-token signing secret | Must be replaced |
| `INITIAL_ADMIN_USERNAME` | Initial administrator | `admin` |
| `INITIAL_ADMIN_PASSWORD` | Initial administrator password | Must be replaced |
| `MAX_UPLOAD_SIZE_BYTES` | Per-file upload limit | `10737418240` |
| `EXPORT_EXPIRY_HOURS` | Export lifetime in hours | `72` |
| `MINIO_*` | Object-storage connection | Example values |
| `MONGODB_*` | MongoDB connection | Example values |
| `REDIS_URL` | Celery queue connection | Example value |

Set `APP_ENV=production` and replace the administrator password, MinIO credentials, and JWT secret before a team deployment. The API refuses to start in production when known defaults remain.

## Development and Tests

```powershell
.\.runtime\venv\Scripts\python.exe -m ruff check backend worker scripts
.\.runtime\venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm test
npx playwright install chromium
npm run test:ui
npm run build
```

The isolated API workflow test is available at `scripts/runtime-e2e.py`. See the [testing guide](docs/testing.md) and [v2.0.0 release checklist](docs/release-checklist.md) for results and remaining validation gates. Mocked browser tests do not constitute real end-to-end acceptance.

## Preparing to upgrade to v2.0.0

Back up MongoDB, MinIO, and deployment configuration and retain old images before upgrading from v1.6.1. Verify project overview, dataset projects, model parameters, deletion impact, and navigation. Startup seeds missing metric definitions without overwriting existing configuration; no manual migration is required. Legacy datasets require projects before editing or copying. Rolling back images does not undo data changes. This preparation does not redeploy Docker.

See the [dataset guide](docs/datasets.md), [model parameters](docs/model-parameters.md), and [v2.0.0 release notes](docs/releases/v2.0.0.md). MLflow integration is not implemented.

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
