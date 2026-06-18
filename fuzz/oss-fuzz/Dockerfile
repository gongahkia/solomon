FROM gcr.io/oss-fuzz-base/base-builder

RUN apt-get update && apt-get install -y curl xz-utils && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/gongahkia/shisa.git shisa
COPY build.sh $SRC/build.sh
WORKDIR $SRC/shisa
