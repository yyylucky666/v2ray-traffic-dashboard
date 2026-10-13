# Contributing

Use Python 3.9+ and run `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
Generate synthetic data with `python3 scripts/demo.py --output /tmp/vtd-demo --serve`.
Optional browser tests are described in `tests/browser.cjs` and the README.

Keep the runtime free of third-party Python/JavaScript dependencies. Changes to
V2Ray integration must preserve original routing decisions, avoid counter reset,
and never silently restart a proxy. New category rules should state their scope.
Use synthetic examples and do not commit credentials, real snapshots or local paths.
