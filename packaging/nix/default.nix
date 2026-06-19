{
  lib,
  stdenv,
  zig,
  zig_0_15 ? zig,
}:

let
  zigForBuild = zig_0_15;
in
assert lib.assertMsg (lib.versionAtLeast zigForBuild.version "0.15.2")
  "shisa requires Zig 0.15.2 or newer";
stdenv.mkDerivation {
  pname = "shisa";
  version = "0.1.0";

  src = lib.cleanSource ../..;

  nativeBuildInputs = [
    zigForBuild
  ];

  dontSetZigDefaultFlags = true;
  zigBuildFlags = [
    "-Dcpu=baseline"
    "-Doptimize=ReleaseFast"
  ];

  doCheck = false;

  meta = {
    description = "Daemon-backed, async-first, cross-shell prompt";
    homepage = "https://github.com/gongahkia/shisa";
    license = lib.licenses.mit;
    mainProgram = "shisa";
    platforms = lib.platforms.unix;
  };
}
