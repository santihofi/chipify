# Examples

[`datasheet.yaml`](datasheet.yaml) is a documented template that shows the full
datasheet format: a swept `parameters` block (lists and the `range`/`linspace`/
`logspace` DSL) and a `tests` block with pass/fail specs, optional captured
signals, and derived `measure` expressions.

[`plugins/run_info_tab.py`](plugins/run_info_tab.py) is a complete TabPlugin
example — copy it into `~/.chipify/plugins/` (or `$CHIPIFY_PLUGINS`) to get a
"Run Info" tab in the GUI; see [PLUGINS.md](../PLUGINS.md) for the plugin API.

## Running it

Chipify is a wrapper around external EDA tools, so to run a sweep end-to-end you
need:

1. **Ngspice** and **Xschem** installed and on your `PATH` (see the top-level
   [README](../README.md#prerequisites)).
2. The **Xschem testbench schematics** referenced by the `tests` keys — here
   `tb_ota_op` and `tb_ota_gain` — together with the PDK/models your netlists
   use. These are design-specific and are **not** included in this repo; replace
   the `tb_*` names with your own testbenches.

   In each testbench's `.control` block, define your scalar measurements as
   ngspice vectors (`let`/`meas`) named exactly as the datasheet keys — e.g.
   `let ve = (v(outp)+v(outn))/2` for a `ve` spec. You do **not** write an
   `echo MY_DATA:` line; Chipify injects it automatically from the datasheet.
   (See the worked `tb_sf_*` benches under `source_follower/tb/`.)

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
