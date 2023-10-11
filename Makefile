.DEFAULT_GOAL := all
IMAGE_NAME ?= stream-demo-server
TAG ?= manual
DOCKER := DOCKER_BUILDKIT=1 docker
SOURCES := stream_transcriber/
ACR_ADDRESS := speechmatics.azurecr.io
ACR_IMAGE_NAME := ${ACR_ADDRESS}/${IMAGE_NAME}

.PHONY: all lint build publish format build-linux-amd64 lint-local unittest unittest-local

all: lint build

lint:
	${DOCKER} build -t ${IMAGE_NAME}:${TAG}-lint --target lint .
	${DOCKER} run --rm --name ${IMAGE_NAME}-lint ${IMAGE_NAME}:${TAG}-lint
lint-local:
	black --check --diff ${SOURCES}
	pylint ${SOURCES}
	pycodestyle ${SOURCES}

format:
	black ${SOURCES}

unittest:
	${DOCKER} build -t ${IMAGE_NAME}:${TAG}-unittest --target unittest .
	${DOCKER} run --rm --name ${IMAGE_NAME}-unittest ${IMAGE_NAME}:${TAG}-unittest
unittest-local:
	AUTH_TOKEN=token pytest -v unittests

build:
	${DOCKER} build -t ${IMAGE_NAME}:${TAG} --target production .

# Build locally an image for linux/amd64
build-linux-amd64:
	${DOCKER} build --platform linux/amd64 -t ${IMAGE_NAME}:${TAG} --target production .

publish:
	docker tag ${IMAGE_NAME}:${TAG} ${ACR_IMAGE_NAME}:${TAG}
	docker image inspect ${ACR_IMAGE_NAME}:${TAG}
	docker push ${ACR_IMAGE_NAME}:${TAG}