# Development

The project uses [uv](https://docs.astral.sh/uv/). The collector itself has no dependencies; pytest, pytest-cov, ruff and Zensical sit in dependency groups.

## Tests and lint

```bash
uv run pytest --cov=gnss_ntp_graphs
uv run ruff check .
uv run ruff format --check .
```

The tests cover config loading and validation, the chrony, ntpd, gpsd and bridge parsers (against the captured output in `tests/fixtures/`), the store and rollups, the statistics, and the commit-message hook. The run fails if total coverage drops below `fail_under` in `pyproject.toml`.

The CI workflow runs the ruff checks and the tests on Python 3.11 and 3.12 for every push and pull request to `main`, and uploads the 3.12 coverage report to Codecov.

## Running against a config

```bash
uv run python -m gnss_ntp_graphs -c deploy/config.toml once
```

`once` polls once and writes every file, then exits. Point `[paths]` at a local folder first, since the defaults are under `/var/lib`. To watch the page, run `run` with the built-in server:

```bash
GNG_PATHS_DB=/tmp/gng/samples.db GNG_PATHS_WWW=/tmp/gng/www GNG_SERVER_SERVE=true \
GNG_SOURCE_BRIDGE_URL=http://192.168.1.50/ \
uv run python -m gnss_ntp_graphs run
```

Then open `http://127.0.0.1:8080/`.

## Documentation

[Zensical](https://zensical.org) builds this site from `docs/` and `zensical.toml`.

```bash
uv run --group docs zensical serve        # live preview on http://127.0.0.1:8000/
uv run --group docs zensical build --strict --clean
```

`--strict` fails on broken links and on pages missing from the navigation. The docs workflow runs a spellcheck (`.github/cspell.json`, British English) and the strict build, then publishes to GitHub Pages when a release is published.
