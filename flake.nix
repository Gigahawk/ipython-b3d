{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        nixpkgs.follows = "nixpkgs";
      };
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs = {
        pyproject-nix.follows = "pyproject-nix";
        uv2nix.follows = "uv2nix";
        nixpkgs.follows = "nixpkgs";
      };
    };

    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, pyproject-nix, uv2nix
    , pyproject-build-systems, treefmt-nix, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        inherit (nixpkgs) lib;
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python312;

        # cadquery-ocp needs vtk 9.3
        vtkDeriv =
          import "${pkgs.path}/pkgs/development/libraries/vtk/generic.nix" {
            #version = "9.3.1";
            majorVersion = "9.3";
            minorVersion = "1";
            sourceSha256 =
              "sha256-g1TsCE6g0tw9I9vkJDgjxL/CcDgtDOjWWJOf1QBhyrg=";
          };
        vtk = (pkgs.callPackage vtkDeriv {
          enablePython = true;
          inherit python;
          #pythonSupport = true;

          # Other stuff that callPackage doesn't fill in for some reason?
          qtdeclarative = pkgs.qt5.qtdeclarative;
          qttools = pkgs.qt5.qttools;
          qtx11extras = pkgs.qt5.qtx11extras;
          qtEnv = pkgs.qt5.qtEnv;
        }).overrideAttrs (old: {
          # cadquery-ocp wheel looks for versioned .so file names
          cmakeFlags = old.cmakeFlags ++ [ "-DVTK_VERSIONED_INSTALL=ON" ];
        });

        workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };
        overlay = workspace.mkPyprojectOverlay { sourcePreference = "wheel"; };
        editableOverlay =
          workspace.mkEditablePyprojectOverlay { root = "$REPO_ROOT"; };
        hacks = pkgs.callPackage pyproject-nix.build.hacks { };

        pyprojectOverrides = final: prev: {
          cadquery-ocp = prev.cadquery-ocp.overrideAttrs (old: {
            buildInputs = (old.buildInputs or [ ]) ++ [ vtk ];

            # TODO: this no longer happens once cadquery was included???
            # HACK: work around ImportError issue
            postInstall = ''
              main_init=$out/${python.sitePackages}/OCP/__init__.py
              echo 'import vtk'$'\n'"$(cat $main_init)" > $main_init
            '';
          });
          pyperclip = prev.pyperclip.overrideAttrs (old: {
            buildInputs = (old.buildInputs or [ ]) ++ [ prev.setuptools ];
          });

          # Example overrides to fix build
          # psycopg2 = prev.psycopg2.overrideAttrs (old: {
          #   buildInputs = (old.buildInputs or [ ]) ++ [
          #     prev.setuptools
          #     pkgs.libpq.pg_config
          #   ];
          # });
          # casadi = hacks.nixpkgsPrebuild {
          #   from = pkgs.python312Packages.casadi;
          #   prev = prev.casadi;
          # };

          ## TODO: Add tests to package?
          ## Based on https://pyproject-nix.github.io/uv2nix/patterns/testing.html
          ## Doesn't seem to work, ipython-b3d package isn't found
          #ipython-b3d = prev.ipython-b3d.overrideAttrs (old: {
          #  passthru = old.passthru // {
          #    tests =
          #      let
          #        _virtualenv = final.mkVirtualEnv "ipython-b3d-pytest-env" workspace.deps.all // {
          #          ipython-b3d = [ "dev" ];
          #        };
          #      in
          #      (old.tests or { })
          #      // {
          #        pytest = pkgs.stdenv.mkDerivation {
          #          name = "${final.ipython-b3d.name}-pytest";
          #          inherit (final.ipython-b3d) src;
          #          nativeBuildInputs = [
          #            virtualenv
          #            _virtualenv
          #          ];
          #          dontConfigure = true;
          #          buildPhase = ''
          #            runHook preBuild
          #            pytest
          #            runHook postBuild
          #          '';
          #        };
          #      };
          #  };
          #});
        };

        pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope (lib.composeManyExtensions [
          pyproject-build-systems.overlays.wheel
          overlay
          pyprojectOverrides
        ]);

        editablePythonSet = pythonSet.overrideScope editableOverlay;
        virtualenv = editablePythonSet.mkVirtualEnv "ipython-b3d-dev-env"
          workspace.deps.all;

        inherit (pkgs.callPackages pyproject-nix.build.util { }) mkApplication;

        treefmtEval = treefmt-nix.lib.evalModule pkgs ./treefmt.nix;
      in {
        packages = {
          ipython-b3d = mkApplication {
            venv = pythonSet.mkVirtualEnv "ipython-b3d-app-env"
              workspace.deps.default;
            package = pythonSet.ipython-b3d;
          };
          default = self.packages.${system}.ipython-b3d;
        };
        formatter = treefmtEval.config.build.wrapper;
        checks = {
          formatting = treefmtEval.config.build.check self;
          # Doesn't seem to work
          # pytest = editablePythonSet.ipython-b3d.passthru.tests.pytest;
        };
        devShells = {
          default = pkgs.mkShell {
            packages = [ virtualenv pkgs.uv pkgs.sphinx pkgs.git ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = editablePythonSet.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            } // lib.optionalAttrs pkgs.stdenv.isLinux {
              LD_LIBRARY_PATH =
                lib.makeLibraryPath pkgs.pythonManylinuxPackages.manylinux1;
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
              . ${virtualenv}/bin/activate
            '';
          };
        };
      });
}
