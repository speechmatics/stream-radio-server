FROM python:3.11-alpine as builder
RUN mkdir /install
WORKDIR /install
COPY requirements.txt /requirements.txt
RUN pip install --prefix="/install" -r /requirements.txt


FROM python:3.11-alpine as production
RUN apk upgrade -U && apk add ffmpeg
COPY --from=builder /install /usr/local
COPY ./stream_transcriber /stream_transcriber
WORKDIR /
EXPOSE 8765
EXPOSE 8000
ENTRYPOINT ["python"]
CMD ["-m", "stream_transcriber.server"]

FROM production as base-dev
RUN apk add --no-cache make
COPY ./requirements-dev.txt /requirements-dev.txt
RUN pip install -r /requirements-dev.txt

FROM base-dev as lint
WORKDIR /
COPY ./Makefile /Makefile
COPY ./setup.cfg /setup.cfg
COPY ./stream_transcriber /stream_transcriber
ENTRYPOINT ["make", "lint-local"]

FROM base-dev as unittest
WORKDIR /
COPY ./stream_transcriber /stream_transcriber
COPY ./unittests /unittests
COPY ./Makefile /Makefile
COPY ./pytest.ini /pytest.ini
ENTRYPOINT [ "make", "unittest-local" ]
