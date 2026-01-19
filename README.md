# landsat

A CLI library for creating datasets of Landsat images from AWS S3.

## Overview

Downloads Landsat ARD data from [AWS Open Data Registry](https://registry.opendata.aws/glad-landsat-ard/) containing 1deg x 1deg tiles with 16-day composite time series. Supports incremental downloads, parallelization, compression, and cloud filtering.

## Features

- [ ] Incremental download: start, interrupt, and resume downloads
- [ ] Failsafe: automatic retries, atomic writes (temp file + rename)
- [ ] Parallelization: multi-threaded/process downloads
- [ ] Post-process: JPEG2000 compression, cloud filtering
- [ ] Metadata: queryable time series by area and time range
- [ ] Pleasant UX: logging, Rich colored output, progress bars
- [ ] Reproducibility: minimal config file for dataset description
- [ ] User-friendly config: specify country/region, auto-detect AOI
- [ ] Versioning: CHANGELOG for release notes
- [ ] Fully typed: complete type annotations
- [ ] No GDAL: rasterio only
- [ ] Best-effort estimates: download time, final dataset size
- [ ] Testing: comprehensive test coverage

## Installation

```bash
pip install -e .
pip install -e ".[dev]"
pre-commit install
```

## Usage

```bash
landsat --help
```

## Configuration

See configuration docs for details on defining dataset specifications.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.
