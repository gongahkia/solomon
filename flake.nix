# SPDX-License-Identifier: MIT

{
  description = "Reproducible Shibahama development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              cargo
              clippy
              git
              nodejs_22
              pnpm
              pre-commit
              python314
              rustc
              rustfmt
            ];

            shellHook = ''
              export PATH="${pkgs.python314}/bin:$PATH"
              export RUST_BACKTRACE=1
              echo "Shibahama dev shell: run scripts/ci/rust.sh"
            '';
          };
        }
      );
    };
}
