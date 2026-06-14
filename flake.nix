# SPDX-License-Identifier: Apache-2.0

{
  description = "Solomon local development shell with Python and uv";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.git
            pkgs.python312
            pkgs.uv
            pkgs.gitleaks
          ];
          shellHook = ''
            echo "Solomon dev shell."
          '';
        };
      });
}
