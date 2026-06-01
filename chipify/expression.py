"""
expression.py – Sandboxed expression evaluator for Chipify.

Backs all eval() / df.eval() call-sites with a safe evaluator built on
asteval (security) + numexpr (performance on hot vectorised paths).

Public API
----------
SafeEvaluator
    .evaluate_scalar(expr, names)            – general scalar/array eval
    .evaluate_spice_measure(expr, results)   – VACASK .raw measure exprs
    .evaluate_vector(expr, columns)          – numexpr fast-path, asteval fallback
    .evaluate_dataframe_column(df, t, expr)  – replaces df.eval(engine='python')
    .sanitise_key(name)                      – SPICE name → Python identifier
    .sanitise_spice_expr(expr)               – translate v(out) → v_out_ in-expr

ExpressionError                              – raised on evaluation failures
"""
from __future__ import annotations

import re
import logging
from typing import Any, Mapping

import numpy as np
import numpy.typing as npt
import pandas as pd
from asteval import Interpreter

log = logging.getLogger("chipify.expression")

_RE_SANITISE = re.compile(r"[^a-zA-Z0-9_]")
_RE_SPICE_CALL = re.compile(r"([a-zA-Z_]\w*)\(([^()]+)\)")
_RE_VALID_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Dangerous builtins that must never be reachable from a user expression.
# asteval's default symbol table ships some of these (e.g. ``open`` in 1.0.x), so
# we strip them explicitly rather than trusting whatever asteval happens to expose.
_BLOCKED_BUILTINS = frozenset({
    "open", "eval", "exec", "compile", "__import__", "input",
    "globals", "locals", "vars", "memoryview", "breakpoint", "help",
    "getattr", "setattr", "delattr",
})


class ExpressionError(Exception):
    """Raised when a user expression cannot be parsed or evaluated safely."""


def _default_helpers() -> dict[str, Any]:
    """Return the numpy helpers available in all evaluator contexts."""
    return {
        "db": lambda x: 20.0 * np.log10(np.abs(np.asarray(x, dtype=float))),
        "last": lambda x: float(np.asarray(x, dtype=float)[-1]),
        "first": lambda x: float(np.asarray(x, dtype=float)[0]),
    }


def _run_interp(interp: Interpreter, expr: str) -> Any:
    """Execute *expr* in *interp* and raise ExpressionError on any error."""
    result = interp(expr)
    if interp.error:
        msgs = []
        for holder in interp.error:
            try:
                msgs.append(str(holder.msg))
            except Exception:
                msgs.append(repr(holder))
        interp.error = []
        raise ExpressionError("; ".join(msgs))
    return result


class SafeEvaluator:
    """
    Thread-safe sandboxed evaluator.

    Each evaluate_* call creates a fresh asteval.Interpreter so that symbol
    tables from previous calls never bleed into subsequent ones.  This also
    means instances are safe to share across threads.
    """

    def __init__(
        self,
        helpers: dict[str, Any] | None = None,
        use_numpy: bool = True,
    ) -> None:
        self._use_numpy = use_numpy
        self._helpers: dict[str, Any] = _default_helpers()
        if helpers:
            self._helpers.update(helpers)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _make_interp(self, extra: dict[str, Any] | None = None) -> Interpreter:
        interp = Interpreter(use_numpy=self._use_numpy)
        # Remove dangerous builtins before adding user names, so a data name that
        # happens to be e.g. "open" can still shadow it as harmless data.
        for name in _BLOCKED_BUILTINS:
            interp.symtable.pop(name, None)
        interp.symtable.update(self._helpers)
        if extra:
            interp.symtable.update(extra)
        return interp

    # ── Utility ───────────────────────────────────────────────────────────────

    def sanitise_key(self, name: str) -> str:
        """Replace every non-identifier character with underscore."""
        return _RE_SANITISE.sub("_", name)

    def sanitise_spice_expr(self, expr: str) -> str:
        """Translate SPICE-style function calls: v(out) → v_out_, i(R1) → i_R1_."""
        return _RE_SPICE_CALL.sub(
            lambda m: self.sanitise_key(m.group(1) + "_" + m.group(2) + "_"),
            expr,
        )

    # ── Evaluation entry-points ───────────────────────────────────────────────

    def evaluate_scalar(
        self,
        expr: str,
        names: Mapping[str, Any],
    ) -> Any:
        """
        Evaluate *expr* in a namespace of *names* (numpy arrays or scalars).

        Raises ExpressionError on syntax errors or disallowed constructs.
        """
        interp = self._make_interp(dict(names))
        return _run_interp(interp, expr)

    def evaluate_spice_measure(self, expr: str, results: dict[str, Any]) -> Any:
        """
        Evaluate a VACASK/SPICE measure expression.

        Mirrors the original simulator._eval_measure_expr logic:
        signal names are sanitised (v_out_ etc.) and the expression is
        translated accordingly before asteval receives it.

        Replaces: ``eval(expr_safe, namespace)`` in simulator.py.
        """
        namespace: dict[str, Any] = {
            self.sanitise_key(k): np.asarray(v, dtype=float)
            for k, v in results.items()
        }
        safe_expr = self.sanitise_spice_expr(expr)
        log.debug("evaluate_spice_measure: %r → %r", expr, safe_expr)
        return self.evaluate_scalar(safe_expr, namespace)

    def evaluate_vector(
        self,
        expr: str,
        columns: Mapping[str, npt.NDArray[Any]],
    ) -> npt.NDArray[Any]:
        """
        Evaluate *expr* against column arrays, returning a numpy array.

        Fast path: numexpr (plain arithmetic, no custom helpers).
        Fallback: asteval (supports db(), last(), first(), …).

        Used by the transient-overlay hot path in plot_manager.py.
        """
        col_dict = dict(columns)

        # numexpr fast path (only handles plain arithmetic / comparisons)
        try:
            import numexpr as ne
            result: npt.NDArray[Any] = ne.evaluate(expr, local_dict=col_dict)
            return result
        except Exception:
            pass  # expression uses helpers or has unsupported syntax → fall through

        interp = self._make_interp(col_dict)
        raw = _run_interp(interp, expr)
        return np.asarray(raw)

    def evaluate_dataframe_column(
        self,
        df: pd.DataFrame,
        target: str,
        expr: str,
    ) -> pd.DataFrame:
        """
        Add a new column *target* = *expr* to *df* safely.

        - Column names that are not valid Python identifiers (e.g. ``v(out)``)
          are translated to their sanitised form in both the namespace and the
          expression text before evaluation.
        - Numeric columns are converted to float arrays; non-numeric columns
          are passed as-is so that string predicates still work.
        - Returns a copy of *df* with *target* added.

        Replaces: ``df.eval(f"{name} = {expr}", engine='python')`` calls.
        """
        if not _RE_VALID_IDENT.match(target):
            raise ValueError(f"Invalid column name {target!r}: must be a Python identifier.")

        namespace: dict[str, Any] = {}
        translated_expr = expr

        # Process longest names first to prevent partial replacement of shorter ones.
        for col in sorted(df.columns, key=len, reverse=True):
            col_s = str(col)
            arr = df[col].to_numpy()
            try:
                arr = arr.astype(float)
            except (ValueError, TypeError):
                pass  # leave non-numeric columns as-is

            if col_s.isidentifier():
                namespace[col_s] = arr
            else:
                safe = self.sanitise_key(col_s)
                namespace[safe] = arr
                if col_s in translated_expr:
                    translated_expr = translated_expr.replace(col_s, safe)

        log.debug("evaluate_dataframe_column %r: %r → %r", target, expr, translated_expr)
        result = self.evaluate_scalar(translated_expr, namespace)
        out = df.copy()
        out[target] = result
        return out


# Module-level singleton – callers can use this directly or instantiate their own.
default_evaluator = SafeEvaluator()
