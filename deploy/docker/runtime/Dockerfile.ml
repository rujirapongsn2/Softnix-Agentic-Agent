FROM python:3.11-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN python -m pip install --upgrade pip \
    && python -m pip install \
        numpy \
        pandas \
        scipy \
        scikit-learn \
        matplotlib \
        requests \
        beautifulsoup4 \
        lxml

