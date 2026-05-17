## 1.0.0 (2026-02-17)

### Feat

- major overhaul of tui style and functionality

### Fix

- **ci.yml**: use uvx to run ruff and ty

## 0.2.0 (2026-02-15)

### Feat

- add portfolio and instrument charts, fix auth, clean up types

### Fix

- uppercase idp field in signicatStart payload

## 0.1.0 (2026-02-11)

### Feat

- **Major-developments-in-the-app-including-creation-of-a-TUI-for-accessing-Nordnet-data,-unit-testing,-and-Pydantic-validation-of-API-responses**: create tui for nordpy
- initial commit

## v1.3.0 (2026-05-17)

### Feat

- **accounts**: sort accounts by total (default) with sort dialog
- **accounts**: add AccountSortDialog modal
- **accounts**: add stable sort_accounts ordering function
- **accounts**: add SortField/SortSpec and account_total

### Fix

- **models**: type before-validators as Any to satisfy ty
- **accounts**: use str/Enum mixin so SortField works on Python 3.10
- **accounts**: sum holdings in account currency for mixed-currency accounts

## v1.2.0 (2026-02-18)

### Feat

- **app.py**: add --version flag to check tui version

### Fix

- commitizen version bumping process fix
- fix date picker and add filter reset button
- **accounts.py**: await container removal before re-population during refresh of accounts page
- **BrowserClient,-auth.py,-export.py**: security fixes

### Refactor

- harmonize version number

## v1.1.0 (2026-02-17)

### Fix

- **auth.py**: fix the redirect chain after cpr number validation

## v1.0.1 (2026-02-17)

### Feat

- major overhaul of tui style and functionality
- add portfolio and instrument charts, fix auth, clean up types
- **Major-developments-in-the-app-including-creation-of-a-TUI-for-accessing-Nordnet-data,-unit-testing,-and-Pydantic-validation-of-API-responses**: create tui for nordpy
- initial commit

### Fix

- **ci.yml**: use uvx to run ruff and ty
- uppercase idp field in signicatStart payload
