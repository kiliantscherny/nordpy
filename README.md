<p align="center">
  <img src="static/nordpy-logo.png" alt="nordpy" width="200" />
</p>

<h1 align="center">nordpy</h1>

<p align="center">
  A terminal UI for browsing and exporting your Nordnet portfolio data.
  <br>
  <a href="https://pypi.org/project/nordpy/"><img alt="PyPI - Version" src="https://img.shields.io/pypi/v/nordpy?style=flat&logo=python&logoColor=orange&label=nordpy&labelColor=teal&color=navy"></a>
</p>

<p align="center">
<img src="https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12%20|%203.13-3776AB?logo=python&logoColor=white" alt="Python versions" />
<a href="https://github.com/j178/prek"><img src="https://img.shields.io/badge/prek-enabled-brightgreen?logo=pre-commit&logoColor=white" alt="prek" style="max-width:100%;"></a>
<a href="https://github.com/astral-sh/uv"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json" alt="uv" style="max-width:100%;"></a>
<a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff" style="max-width:100%;"></a>
<a href="https://github.com/astral-sh/ty"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json" alt="ty" style="max-width:100%;"></a>
<a href="https://github.com/tox-dev/tox-uv"><img src="https://img.shields.io/badge/tox-testing-1C1C1C?logo=tox&logoColor=white" alt="tox" alt="tox" style="max-width:100%;"></a>
<a href="https://pydantic.dev/"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/pydantic/pydantic/main/docs/badge/v2.json" alt="Pydantic" style="max-width:100%;"></a>
<a href="https://github.com/commitizen-tools/commitizen"><img src="https://img.shields.io/badge/commitizen-friendly-brightgreen.svg" alt="Pydantic" style="max-width:100%;"></a>
<br>
<a href="https://github.com/kiliantscherny/nordpy/actions/workflows/ci.yml"><img src="https://github.com/kiliantscherny/nordpy/actions/workflows/ci.yml/badge.svg" alt="CI" style="max-width:100%;"></a>
<a href="https://github.com/kiliantscherny/nordpy/actions/workflows/release.yml"><img src="https://github.com/kiliantscherny/nordpy/actions/workflows/release.yml/badge.svg" alt="Release to PyPI" style="max-width:100%;"></a>

---

> [!CAUTION]
> **Disclaimer** – This tool is provided as-is, with no warranty of any kind. **Use it at your own risk**.
>
> This project is not affiliated in any way with Nordnet nor MitID.
>
> The author assumes no liability for any loss, damage, or misuse arising from the use of this software. You are solely responsible for securing any exported data and ensuring it is only accessible to you.

## Features

- Browse accounts, balances, holdings, transactions, trades, and orders
- **Portfolio value chart** and **instrument price charts** in the terminal
- **Sparkline trends** on holdings (3-month price history via yfinance)
- Export data to **CSV**, **Excel**, or **DuckDB**
- Session persistence with automatic re-authentication
- Headless export mode (no TUI) for scripting
- SOCKS5 proxy support

## How It Works

nordpy authenticates with Nordnet through the same MitID flow your browser uses – it simply performs the login via Nordnet's API directly from the terminal, rather than through a web page. Once authenticated, it fetches your portfolio data using Nordnet's standard API endpoints.

> [!IMPORTANT]
> **Privacy** – nordpy does **not** collect, transmit, or store any of your personal information. Your credentials are sent directly to MitID and Nordnet – never to any third-party server. No telemetry, analytics, or external services are involved.
>
> Session cookies are saved locally, `0600`, solely to avoid repeated logins:
>
> | | where |
> | --- | --- |
> | session | `$XDG_CONFIG_HOME/nordpy/nordnet-session.json`, or `~/.config/nordpy/…` |
> | log | `$XDG_STATE_HOME/nordpy/nordpy.log`, or `~/.local/state/nordpy/…` |
>
> Both are the same place on every run. `nordpy --logout` deletes the session.

### Quickstart

```bash
# Run with Python 3.10–3.13 and replace <your-mitid-username> with your MitID username
uvx --python 3.13 nordpy --user <your-mitid-username>
```

### Using <code>nordpy</code> (step by step with screenshots)
<figure>
  <figcaption>Sign in with your MitID username</figcaption>
  <img src="static/1.png" alt="Step 1" style="width:100%">
</figure>

<figure>
  <figcaption>Approve the login on your MitID app, then enter your CPR number if prompted</figcaption>
  <img src="static/2.png" alt="Step 2" style="width:100%">
</figure>

<figure>
  <figcaption>If you have authorized correctly, you will see a confirmation message</figcaption>
  <img src="static/3.png" alt="Step 3" style="width:100%">
</figure>

<figure>
  <figcaption>You are now logged in and will see your list of accounts</figcaption>
  <img src="static/4.png" alt="Step 4" style="width:100%">
</figure>

<figure>
  <figcaption>Select an account to view its holdings</figcaption>
  <img src="static/5.png" alt="Step 5" style="width:100%">
</figure>

<figure>
  <figcaption>View the transactions for the selected account</figcaption>
  <img src="static/6.png" alt="Step 6" style="width:100%">
</figure>

<figure>
  <figcaption>See the price history for the selected instrument in your holdings</figcaption>
  <img src="static/7.png" alt="Step 7" style="width:100%">
</figure>


## Requirements

- Python 3.10–3.13
- A Nordnet account with MitID (Danish)

## Installation

nordpy is a command-line tool, not a library. There is nothing here worth
importing, so the way to run it is the way you run any other tool:

```bash
uvx nordpy --user <your-mitid-username>
```

That fetches it, runs it, and leaves nothing behind. If you use it often:

```bash
uv tool install nordpy        # or: pipx install nordpy
nordpy --user <your-mitid-username>
```

> [!TIP]
> `uv add nordpy` would work, but it is not what this is for. Adding a TUI that
> logs you in with MitID to a project's dependencies buys you nothing and ties
> that project to everything nordpy pulls in.

## Usage

### Interactive TUI

```bash
nordpy --user <your-mitid-username>

# Force re-authentication (ignore saved session)
nordpy --user <your-mitid-username> --force-login

# Verbose logging (debug output to stderr, and the log path printed)
nordpy --user <your-mitid-username> --verbose

# Delete saved session and exit
nordpy --logout
```

> [!NOTE]
> The first time you log in, you may be prompted to enter your **CPR number** as part of the MitID verification process. This is a one-time step required by MitID to link your identity – subsequent logins will skip this.

### Headless Export

```bash
nordpy --user <your-mitid-username> --export csv
nordpy --user <your-mitid-username> --export xlsx
nordpy --user <your-mitid-username> --export duckdb

# Export to a specific folder
nordpy --user <your-mitid-username> --export csv --output-dir ~/my-exports
```

Exported files are saved to the `exports/` directory.

> [!WARNING]
> Exported files contain sensitive financial data. Make sure you do not share these filesnor commit them to version control. Keep your exports in a secure location accessible only to you.

### Keybindings

| Key | Action |
|-----|--------|
| `Enter` | Select account / view instrument chart |
| `Tab` | Switch between tabs |
| `e` | Export current view |
| `r` | Refresh data |
| `Backspace` / `Esc` | Go back / quit |
| `q` | Quit |

## Development

```bash
git clone https://github.com/kiliantscherny/nordpy.git
cd nordpy
uv sync --dev
```

### Running checks

```bash
# Run all checks (tests on Python 3.10–3.13, lint, type check)
uv run tox

# Run tests only
uv run pytest

# Run tests with coverage
uv run pytest --cov=nordpy --cov-report=term-missing

# Lint
uv run ruff check .

# Type check
uv run ty check
```

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgments

This project includes code from [MitID-BrowserClient](https://github.com/Hundter/MitID-BrowserClient) by Hundter, licensed under the MIT License.

Credit also to [Morten Helmstedt](https://helmstedt.dk/2025/03/hent-dine-nordnet-transaktioner-med-mitid/) for the groundwork of looking into this.
