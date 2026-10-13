# External dependencies

The Python application, installer, tests and web assets in this repository are
licensed under MIT. This repository does not vendor third-party source, domain
list snapshots, fonts, JavaScript frameworks, binary packages or certificates.

- Python: provided by the operating system; [PSF license](https://docs.python.org/3/license.html).
- V2Ray / v2fly-core: installed independently; [MIT license](https://github.com/v2fly/v2ray-core/blob/master/LICENSE).
- Nginx: installed independently; [BSD-style license](https://nginx.org/LICENSE).
- systemd and logrotate: supplied independently by the Linux distribution;
  their own upstream licenses apply.
- acme.sh is an **optional external certificate client**, not included or modified
  by this project. Version 3.1.6 uses [GPL-3.0](https://github.com/acmesh-official/acme.sh/blob/3.1.6/LICENSE.md).
  The MIT license here does not relicense acme.sh or other external programs.
- Playwright is an optional development tool, installed independently;
  [Apache-2.0 license](https://github.com/microsoft/playwright/blob/main/LICENSE).

Example category rules are a small, manually maintained starting list, not a
copy of a third-party domain-list database. They do not claim exhaustive coverage.
