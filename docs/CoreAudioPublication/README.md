# macOS MPVKit-GPL CoreAudio candidate

This package exposes macOS 12+ and the MPVKit-GPL product. Lua remains disabled.
It retains universal arm64/x86_64 dependency slices; downstream application
architecture and runtime acceptance are separate.

Release assets include the eight exact qualified framework ZIPs and
`coreaudio-publication-stage.tar.gz`, containing the complete 46-file historical
stage with its paths preserved: sources, raw commits, attributed patches,
auxiliary build inputs, original builder/receipt, and package wrapper.
The retained manifest SHA-256 is
`3eb8f8dd20ce2de6802b7d080e6df30a69ca00b6706dc408823291576b96616c`.
Its pending-publication statements describe the original September 30 stage.
The new portable-build receipt records the October 2 reconstruction/rebuild.

Extract the stage to a new directory, then run the three colocated Python
helpers from this directory. Install tools explicitly before running; the
driver never installs tools and uses macOS sandbox-exec to deny all network.

```sh
python3 build-mpv-coreaudio-from-stage.py /path/to/stage /path/to/NEW-build \
  --expected-publication-sha256 3eb8f8dd20ce2de6802b7d080e6df30a69ca00b6706dc408823291576b96616c \
  --metal-toolchain /path/to/Metal.xctoolchain \
  --pkg-config-directory /path/to/pkgconfig \
  --external-headers /path/to/include
```

Repeat the last two flags for each declared host directory. Apple/Homebrew SDK
pkg-config shim directories may also be needed for SDK libraries such as zlib.
The driver hashes SDK/header symlink closures and declared tools, checks them
again after building, records relocations, verifies both binary architectures
and fresh CoreAudio objects, and requires every boolean configuration digest to
match the original qualified build. Unexpected autodetection fails validation.

The October 2 fresh offline rebuild passes these checks. Original missing
environment identities remain missing; byte-identical rebuilding is not claimed.
The published binaries are the exact original qualified payloads, rather than
substituted rebuild ZIPs. Fresh remote authentication, ordinary package
resolution, downstream app tests, audible/device/surround/soak acceptance and
supported-platform testing remain downstream responsibilities.
