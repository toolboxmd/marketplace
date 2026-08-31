#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 -B "$here/test_catalog.py"
PYTHONDONTWRITEBYTECODE=1 python3 -B "$here/test_project_record_ingestion.py"
