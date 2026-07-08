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

  buildPhase = ''
    runHook preBuild
    export HOME="$TMPDIR"
    zig build release \
      --prefix "$TMPDIR/install" \
      --cache-dir "$TMPDIR/zig-cache" \
      --global-cache-dir "$TMPDIR/zig-global-cache" \
      --summary all
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out"
    cp -R "$TMPDIR/install/"* "$out/"
    install -Dm644 init/shisa.zsh "$out/share/shisa/init/shisa.zsh"
    install -Dm644 init/shisa.bash "$out/share/shisa/init/shisa.bash"
    install -Dm644 init/shisa.fish "$out/share/shisa/init/shisa.fish"
    install -Dm644 init/shisa.nu "$out/share/shisa/init/shisa.nu"
    install -Dm644 init/shisa.ps1 "$out/share/shisa/init/shisa.ps1"
    cp -R themes "$out/share/shisa/themes"
    cp -R examples "$out/share/shisa/examples"
    runHook postInstall
  '';

  doCheck = false;

  meta = {
    description = "Daemon-backed, async-first, cross-shell prompt";
    homepage = "https://github.com/gongahkia/shisa";
    license = lib.licenses.mit;
    mainProgram = "shisa";
    platforms = lib.platforms.unix;
  };
}
