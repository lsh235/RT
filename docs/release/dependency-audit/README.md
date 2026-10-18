# Dependency audit evidence

Snapshot collected 2026-10-19 from a copy of the R11 source tree. Each JSON inventory records the exact resolved distributions (direct/transitive), metadata license fields, classifiers, distribution license/notice paths with file hashes and sizes, and selected wheel URL/archive SHA-256. Temporary absolute extraction paths were removed when making these records repository-resident. License/notice file contents themselves are not vendored here.

## Environments

| Python | Extra | Distribution count | Inventory |
| --- | --- | ---: | --- |
| 3.12 | `semantic` | 32 | [`py312-semantic-resolved-inventory.json`](py312-semantic-resolved-inventory.json) |
| 3.12 | `reranker` | 64 | [`py312-reranker-resolved-inventory.json`](py312-reranker-resolved-inventory.json) |
| 3.12 | `token-preview` | 20 | [`py312-token-preview-resolved-inventory.json`](py312-token-preview-resolved-inventory.json) |
| 3.12 | `private-vector` | 32 | [`py312-private-vector-resolved-inventory.json`](py312-private-vector-resolved-inventory.json) |
| 3.12 | `agents` | 21 | [`py312-agents-resolved-inventory.json`](py312-agents-resolved-inventory.json) |
| 3.11 | `agents` | 21 | [`py311-agents-resolved-inventory.json`](py311-agents-resolved-inventory.json) |
| 3.10 | `agents` | 12 | [`py310-agents-resolved-inventory.json`](py310-agents-resolved-inventory.json) |

The [`index.json`](index.json) summarizes all seven snapshots and missing metadata/file observations. [`python-lock-license-metadata.json`](python-lock-license-metadata.json) is the independent QA capture for the exact 11 distributions in `requirements-dev.lock`. The wheel and Docker image path inventories are [`wheel-file-manifest.txt`](wheel-file-manifest.txt) and [`image-file-manifest.txt`](image-file-manifest.txt); those manifests confirm the two bundled sample paths are present. An initial inspected wheel SHA-256 is `5d4734bbbdf484dd6b87f5da23f954ff59f79022254cd948858c0c31dfc0ebf3`; its inspected Docker image ID is `sha256:3bd85264bcf9ec640e6eaf4a59753d25a962c8360a838fda5e477dc96a7b0a4e`, and its rootfs tar SHA-256 is `91c8d0445b2d194826a476e5386431e4de8a9bb2ac301dc42f36873e92663dfd`. The final same-host/toolchain repeated-build results and broader regression evidence are recorded in the [independent R11 QA report](../../acceptance/v1.16.0-independent-qa.md).

## Collection command and limits

The collector created isolated virtual environments from Python 3.12, 3.11, and 3.10 interpreters. For each row it installed the corresponding optional extra from the temporary source copy using this command shape, then read installed distribution metadata and license/notice paths without importing application modules or invoking model code:

```sh
python -m pip install --disable-pip-version-check \
  --report <environment>-pip-report.json \
  -e "/path/to/source-copy[EXTRA]"
```

The pip reports and temporary environments were not copied into the repository. No product tests ran and no model weights were downloaded. These are point-in-time resolutions of declared version ranges, not lockfiles; results can vary by index state, Python version, operating system, and architecture. Several distributions lacked license metadata or license/notice files, as listed in the inventories. Optional license/notice review and model artifact license review remain **INCOMPLETE**. Presence or absence in collected package metadata is not a legal conclusion or proof of notice delivery in project releases.

The manifests verify observed file paths and hashes for the inspected artifacts. The independent R11 QA report separately records two matching wheel builds and two same-project no-cache Docker builds with identical image ID, config, rootfs layers, and saved archive on the tested host/toolchain. This does not establish cross-host/toolchain reproducibility or freeze ranged build-system dependencies. Sample redistribution permission remains **UNRESOLVED / NOT RUN** despite confirmed inclusion.
