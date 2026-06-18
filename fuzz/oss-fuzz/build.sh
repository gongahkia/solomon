#!/bin/bash -eu

ZIG_VERSION="${ZIG_VERSION:-0.15.2}"
ZIG_DIR="$WORK/zig-$ZIG_VERSION"

if [ ! -x "$ZIG_DIR/zig" ]; then
  mkdir -p "$WORK"
  curl -fsSL "https://ziglang.org/download/$ZIG_VERSION/zig-x86_64-linux-$ZIG_VERSION.tar.xz" -o "$WORK/zig.tar.xz"
  tar -C "$WORK" -xf "$WORK/zig.tar.xz"
  mv "$WORK/zig-x86_64-linux-$ZIG_VERSION" "$ZIG_DIR"
fi

"$ZIG_DIR/zig" build-lib \
  -O ReleaseSafe \
  -target native-native-gnu \
  --dep frame \
  --dep context \
  -Mshisa_fuzz="$SRC/shisa/fuzz/oss-fuzz/shisa_fuzz.zig" \
  -Mframe="$SRC/shisa/src/proto/frame.zig" \
  -Mcontext="$SRC/shisa/src/plugin/context.zig" \
  -femit-bin="$WORK/libshisa_fuzz.a"

"$CXX" $CXXFLAGS -std=c++17 \
  "$SRC/shisa/fuzz/oss-fuzz/shisa_fuzzer.cc" \
  "$WORK/libshisa_fuzz.a" \
  $LIB_FUZZING_ENGINE \
  -o "$OUT/shisa_fuzzer"
