# AppImage Pipeline

Build on Linux after installing `appimagetool`:

```sh
packaging/appimage/build-appimage.sh
```

The script runs `zig build release`, stages an AppDir under `zig-out/appimage/Shisa.AppDir`, then writes `zig-out/appimage/Shisa-<version>-x86_64.AppImage`.

Use `--appdir-only` to validate AppDir layout without requiring `appimagetool`.
