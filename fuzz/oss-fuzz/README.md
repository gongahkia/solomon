# OSS-Fuzz integration

This directory mirrors the files expected under `oss-fuzz/projects/shisa/`.

The project uses a C++ libFuzzer driver that links a Zig fuzz library.

Local check from an OSS-Fuzz checkout:

```sh
python3 infra/helper.py build_image shisa
python3 infra/helper.py build_fuzzers --sanitizer address shisa
python3 infra/helper.py check_build shisa
```
