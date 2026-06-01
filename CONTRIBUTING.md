# Contributing to Chipify

Thanks for your interest in improving Chipify! This guide covers the basics for
getting set up and submitting changes.

## Development setup

```bash
git clone https://github.com/santihofi/chipify.git
cd chipify
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1
pip install -e ".[fast]"
pip install pytest mypy pandas-stubs types-PyYAML
```

To run a full simulation you also need **Ngspice** and **Xschem** on your `PATH`
(see the [README](README.md#prerequisites)). The test suite and type checks do
not require them.

## Before opening a pull request

- **Run the tests:** `pytest`
- **Type-check the typed core:**
  ```bash
  python -m mypy chipify/expression.py chipify/schema.py chipify/util.py \
      chipify/app_config.py chipify/settings.py chipify/gui/state.py \
      chipify/gui/tabs/base.py
  ```
  CI runs both of these on every push and pull request.
- Keep changes focused and describe *why* in the PR.

## Architecture conventions

A few invariants keep the codebase testable and maintainable (see
[context.md](context.md) for the full picture):

1. **Services and model modules** (`gui/services/`, `gui/state.py`,
   `expression.py`, `schema.py`) **must not import tkinter/customtkinter** — this
   keeps them unit-testable without a display.
2. **Tabs/UI never call `simulator.*` directly** — dispatch through a controller.
3. **All expression evaluation goes through `SafeEvaluator`** (`expression.py`);
   never use raw `eval()`/`exec()` on user input.
4. Application state is mutated only through `AppState`.

## Reporting bugs / requesting features

Please use the GitHub issue templates. Include your OS, Python version, and the
Ngspice/Xschem versions when reporting simulation problems.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
