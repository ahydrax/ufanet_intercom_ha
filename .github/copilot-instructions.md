# Copilot Instructions

## Project overview

Home Assistant custom integration (`custom_components/ufanet/`) for Ufanet intercom systems (Russia). Distributed via HACS. Based on the [integration_blueprint](https://github.com/ludeeus/integration_blueprint) template.

Two platforms: **button** (open intercom door) and **camera** (RTSP stream + screenshots). All code lives under `custom_components/ufanet/`.

## Build & lint

```bash
# Lint and auto-fix (format + check)
scripts/lint

# Or run ruff directly
ruff check .            # lint only
ruff format . --check   # format check only
ruff check . --fix      # lint with auto-fix
```

Ruff is configured in `.ruff.toml` with `select = ["ALL"]` targeting Python 3.13. CI runs `ruff check .` and `ruff format . --check` (no auto-fix).

There are no tests in this project.

## Development environment

A devcontainer (`.devcontainer.json`) provides a ready-to-use HA instance:

```bash
scripts/setup    # install pip dependencies
scripts/develop  # start HA on port 8123 with custom_components on PYTHONPATH
```

The `config/configuration.yaml` is used for the local HA instance.

## Architecture

### Authentication flow

`UfanetApiClient` (in `api.py`) manages JWT authentication against `https://dom.ufanet.ru/`:

1. Initial login via contract number + password → receives access + refresh tokens
2. Access token auto-refreshes using the refresh token
3. If refresh token expires, falls back to password-based re-login
4. Token updates are propagated via `on_token_update` callbacks

### Credential storage

Credentials (refresh token, expiration, password) are stored in HA's secure storage (`Store`), **not** in `config_entry.data`. The config entry only holds the contract number and intercom list. Each platform re-reads credentials from the store at runtime.

### Platform pattern

Both `button.py` and `camera.py` follow the same pattern:
1. Read platform data from `hass.data[DOMAIN][entry.entry_id]`
2. Get the `Store` reference and contract from platform data
3. Load password from secure storage
4. Create an `UfanetApiClient` instance with credentials
5. Define a `save_token` callback to persist token updates

### Entity identification

- Unique IDs use the contract number as prefix: `{contract}_{intercom_id}_open` for buttons, `{entry_id}_{camera_number}` for cameras
- All entities share a single device per contract: `DeviceInfo(identifiers={(DOMAIN, contract)})`

## Key conventions

- All modules use `from __future__ import annotations` and `TYPE_CHECKING` guards for type-only imports
- Ruff `noqa` comments are used where intentional rule suppression is needed (e.g., `BLE001` for broad exception catches, `PLR0912` for complex flows)
- Translation keys are defined in `strings.json`; translated files live in `translations/`
- The integration domain is `ufanet` (defined in `const.py` and `manifest.json`)
