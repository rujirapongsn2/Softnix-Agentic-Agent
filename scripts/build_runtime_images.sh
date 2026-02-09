#!/usr/bin/env bash
set -euo pipefail

DATA_TAG="${1:-softnix/runtime-data:py311}"
ML_TAG="${2:-softnix/runtime-ml:py311}"

echo "[build-runtime-images] building data image: ${DATA_TAG}"
docker build -f deploy/docker/runtime/Dockerfile.data -t "${DATA_TAG}" .

echo "[build-runtime-images] building ml image: ${ML_TAG}"
docker build -f deploy/docker/runtime/Dockerfile.ml -t "${ML_TAG}" .

echo "[build-runtime-images] done"
echo "Set these in .env:"
echo "  SOFTNIX_EXEC_CONTAINER_IMAGE_DATA=${DATA_TAG}"
echo "  SOFTNIX_EXEC_CONTAINER_IMAGE_ML=${ML_TAG}"

