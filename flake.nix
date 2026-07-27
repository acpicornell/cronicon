{
  description = "Cronicon Mayoricense (Palma, 1881) - OCR pipeline toolchain";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };

        # spa_old is Tesseract's model for 19th-century Spanish typography and is
        # the primary candidate here; spa is kept for comparison. The Cronicon
        # quotes Catalan and Latin documents at length, hence cat and lat. osd
        # lets us detect rotated or skewed leaves rather than silently OCRing them
        # sideways.
        tesseract = pkgs.tesseract.override {
          enableLanguages = [ "spa_old" "spa" "cat" "lat" "eng" "osd" ];
        };
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            tesseract
            pkgs.uv          # Python environment, locked by uv.lock
            pkgs.python312   # interpreter base for uv venv
            pkgs.openjpeg    # JPEG 2000, for the Internet Archive JP2 leaves
            pkgs.jq
          ];

          shellHook = ''
            echo "cronicon devShell"
            echo "  tesseract $(tesseract --version 2>&1 | head -1 | cut -d' ' -f2)"
            echo "  languages: $(tesseract --list-langs 2>/dev/null | tail -n +2 | tr '\n' ' ')"
            echo
            echo "  Python: uv sync   (creates .venv from uv.lock)"
          '';
        };
      });
}
