# Examples

[`datasheet.yaml`](datasheet.yaml) is a documented template that shows the full
datasheet format: a swept `parameters` block (lists and the `range`/`linspace`/
`logspace` DSL) and a `tests` block with pass/fail specs, optional captured
signals, and derived `measure` expressions.

## Running it

Chipify is a wrapper around external EDA tools, so to run a sweep end-to-end you
need:

1. **Ngspice** and **Xschem** installed and on your `PATH` (see the top-level
   [README](../README.md#prerequisites)).
2. The **Xschem testbench schematics** referenced by the `tests` keys — here
   `tb_ota_op` and `tb_ota_gain` — together with the PDK/models your netlists
   use. These are design-specific and are **not** included in this repo; replace
   the `tb_*` names with your own testbenches.

Then place the datasheet in your input folder (default `datasheets/`) and run:

```bash
chipify-cli -c datasheet.yaml          # headless
# or open the GUI and select it:
chipify
```

Results are written to the output folder (default `out/`).

## Validating the format without simulating

You can confirm a datasheet parses against the schema (no Ngspice/Xschem needed):

```bash
python -c "import yaml; from chipify.schema import validate_datasheet; \
validate_datasheet(yaml.safe_load(open('examples/datasheet.yaml'))); print('OK')"
```
