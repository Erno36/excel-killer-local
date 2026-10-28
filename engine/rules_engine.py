"""
engine/rules_engine.py — Motor de reglas de negocio.

Crea columnas calculadas sobre el DataFrame resultado del cruce.
Sin imports de PySide6. Testeable en forma aislada.
RN-019: no registra valores de celdas, value_true/value_false ni literales de formulas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.models import BusinessRule, RuleCondition
from engine._date_utils import parse_date_flexible

# ---------------------------------------------------------------------------
# Constantes de validacion
# ---------------------------------------------------------------------------

RULE_TYPES_VALIDOS = frozenset({"if_then_else", "formula", "date_diff"})

CONDITION_OPERATORS = frozenset({
    "==", "!=", "<", "<=", ">", ">=",
    "contiene", "es_vacio", "no_es_vacio",
})


# ---------------------------------------------------------------------------
# Funciones internas de evaluacion de condiciones
# ---------------------------------------------------------------------------

def _eval_condition(df: pd.DataFrame, cond: RuleCondition) -> pd.Series:
    """
    Evalua una RuleCondition sobre el DataFrame y retorna una Serie booleana.
    No lanza — filas con datos invalidos para la comparacion quedan como False.
    """
    op = cond.operator
    col = cond.column

    if col not in df.columns:
        return pd.Series(False, index=df.index)

    raw = df[col]
    val = cond.value

    if op == "es_vacio":
        return raw.isna() | (raw.astype(str).str.strip() == "")

    if op == "no_es_vacio":
        return ~(raw.isna() | (raw.astype(str).str.strip() == ""))

    if op == "contiene":
        return raw.astype(str).str.lower().str.contains(
            val.lower(), na=False, regex=False
        )

    if op in ("==", "!="):
        left_s = raw.astype(str).str.lower().str.strip()
        right_s = str(val).lower().strip()
        mask = left_s == right_s
        return mask if op == "==" else ~mask

    # Operadores de comparacion (<, <=, >, >=): intentar numericamente primero
    num_col = pd.to_numeric(raw, errors="coerce")
    try:
        num_val = float(val)
        valid = num_col.notna()
        result = pd.Series(False, index=df.index)
        if op == "<":
            result[valid] = num_col[valid] < num_val
        elif op == "<=":
            result[valid] = num_col[valid] <= num_val
        elif op == ">":
            result[valid] = num_col[valid] > num_val
        elif op == ">=":
            result[valid] = num_col[valid] >= num_val
        return result
    except (ValueError, TypeError):
        # Fallback a comparacion string
        str_col = raw.astype(str).str.lower().str.strip()
        str_val = str(val).lower().strip()
        try:
            if op == "<":
                return str_col < str_val
            elif op == "<=":
                return str_col <= str_val
            elif op == ">":
                return str_col > str_val
            elif op == ">=":
                return str_col >= str_val
        except Exception:
            pass

    return pd.Series(False, index=df.index)


def _combine_conditions(
    df: pd.DataFrame,
    conditions: list[RuleCondition],
    combinator: str,
) -> pd.Series:
    """
    Combina una lista de condiciones con AND u OR.
    Lista vacia → todos True.
    """
    if not conditions:
        return pd.Series(True, index=df.index)

    masks = [_eval_condition(df, c) for c in conditions]
    result = masks[0]
    for m in masks[1:]:
        if combinator == "OR":
            result = result | m
        else:  # AND es el default
            result = result & m
    return result


# ---------------------------------------------------------------------------
# Aplicacion de reglas individuales
# ---------------------------------------------------------------------------

def _apply_if_then_else(df: pd.DataFrame, rule: BusinessRule) -> pd.Series:
    p = rule.params
    raw_conditions = p.get("conditions", [])
    combinator = p.get("combinator", "AND")
    value_true = str(p.get("value_true", ""))
    value_false = str(p.get("value_false", ""))

    if not raw_conditions:
        raise ValueError(
            f"Regla '{rule.output_column}': if_then_else requiere al menos una condicion."
        )

    conditions = [
        RuleCondition(
            column=c.get("column", ""),
            operator=c.get("operator", "=="),
            value=c.get("value", ""),
        )
        for c in raw_conditions
    ]

    mask = _combine_conditions(df, conditions, combinator)
    return pd.Series(
        np.where(mask, value_true, value_false),
        index=df.index,
        dtype=str,
    )


def _resolve_operand(df: pd.DataFrame, token: str) -> pd.Series | float:
    """
    Resuelve un token: si es nombre de columna existente, devuelve la serie
    numerica; si es literal numerico, devuelve float.
    Lanza ValueError si el token no es columna ni literal numerico.
    """
    if token in df.columns:
        return pd.to_numeric(df[token], errors="coerce")
    try:
        return float(token)
    except (ValueError, TypeError):
        raise ValueError(
            f"El operando '{token}' no es una columna del resultado ni un numero valido."
        )


def _apply_formula(df: pd.DataFrame, rule: BusinessRule) -> pd.Series:
    p = rule.params
    left_token = str(p.get("left", "")).strip()
    right_token = str(p.get("right", "")).strip()
    op = p.get("operator", "+")
    fmt = p.get("format", "number")

    if not left_token or not right_token:
        raise ValueError(
            f"Regla '{rule.output_column}': formula requiere 'left' y 'right'."
        )
    if op not in ("+", "-", "*", "/"):
        raise ValueError(
            f"Regla '{rule.output_column}': operador de formula '{op}' no valido."
        )

    left = _resolve_operand(df, left_token)
    right = _resolve_operand(df, right_token)

    if op == "+":
        result = left + right
    elif op == "-":
        result = left - right
    elif op == "*":
        result = left * right
    else:  # "/"
        if isinstance(right, float):
            if right == 0.0:
                result = pd.Series(np.nan, index=df.index)
            else:
                result = left / right
        else:
            # Vectorizado: division por cero → NaN sin lanzar
            with np.errstate(divide="ignore", invalid="ignore"):
                result = left / right.replace(0, np.nan)

    if fmt == "text":
        # Convertir a string con 2 decimales; NaN → ""
        def _fmt(v):
            if pd.isna(v):
                return ""
            try:
                return f"{float(v):.2f}"
            except (ValueError, TypeError):
                return ""
        return result.apply(_fmt).astype(str)
    else:
        return pd.Series(result, index=df.index)


def _apply_date_diff(df: pd.DataFrame, rule: BusinessRule) -> pd.Series:
    p = rule.params
    col_a = str(p.get("col_a", "")).strip()
    col_b = str(p.get("col_b", "")).strip()
    unit = p.get("unit", "days")
    absolute = bool(p.get("absolute", False))

    if not col_a or not col_b:
        raise ValueError(
            f"Regla '{rule.output_column}': date_diff requiere 'col_a' y 'col_b'."
        )
    if col_a not in df.columns:
        raise ValueError(
            f"Regla '{rule.output_column}': columna '{col_a}' no existe en el resultado."
        )
    if col_b not in df.columns:
        raise ValueError(
            f"Regla '{rule.output_column}': columna '{col_b}' no existe en el resultado."
        )

    def _safe_parse(val) -> object:
        """Parsea una celda a datetime o retorna None si no es parseable."""
        if val is None:
            return None
        try:
            if pd.isna(val):
                return None
        except (TypeError, ValueError):
            pass
        return parse_date_flexible(str(val))

    def _diff_row(idx):
        da = _safe_parse(df.loc[idx, col_a])
        db = _safe_parse(df.loc[idx, col_b])
        if da is None or db is None:
            return np.nan
        days = (da - db).days
        if unit == "months":
            days = days // 30
        elif unit == "years":
            days = days // 365
        return abs(days) if absolute else days

    values = [_diff_row(i) for i in df.index]
    return pd.Series(values, index=df.index)


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def apply_rule(df: pd.DataFrame, rule: BusinessRule) -> pd.DataFrame:
    """
    Aplica una regla al DataFrame. Retorna NUEVO DataFrame con output_column
    anhadida o reemplazada. No modifica el original.

    Lanza ValueError si el rule_type no es valido o si hay parametros
    obligatorios faltantes.
    Para errores de evaluacion por datos (division por cero, fecha no parseable):
    comportamiento conservador — la celda recibe "" o NaN, sin lanzar.
    """
    if rule.rule_type not in RULE_TYPES_VALIDOS:
        raise ValueError(
            f"rule_type '{rule.rule_type}' no valido. "
            f"Valores permitidos: {sorted(RULE_TYPES_VALIDOS)}"
        )

    if rule.rule_type == "if_then_else":
        new_col = _apply_if_then_else(df, rule)
    elif rule.rule_type == "formula":
        new_col = _apply_formula(df, rule)
    else:  # date_diff
        new_col = _apply_date_diff(df, rule)

    result = df.copy()
    result[rule.output_column] = new_col
    return result


def apply_all_rules(df: pd.DataFrame, rules: list[BusinessRule]) -> pd.DataFrame:
    """
    Aplica todas las reglas en orden. Retorna nuevo DataFrame.
    Si una regla falla completamente (ValueError de config), la ignora y continua.
    """
    current = df.copy()
    for rule in rules:
        try:
            current = apply_rule(current, rule)
        except ValueError:
            # Regla mal configurada: ignorar y continuar con el resto
            pass
    return current


def preview_rule(
    df: pd.DataFrame,
    rule: BusinessRule,
    n: int = 5,
) -> list[tuple[str, str]]:
    """
    Aplica la regla a las primeras n filas.
    Retorna lista de (fila_resumen, valor_resultado).
    fila_resumen: valores de las columnas involucradas, separados por " | ".
    No lanza — retorna lista vacia en error.
    """
    try:
        subset = df.head(n)
        if subset.empty:
            return []

        result_df = apply_rule(subset, rule)
        new_col_values = result_df[rule.output_column]

        # Determinar columnas involucradas segun el tipo
        involved: list[str] = []
        p = rule.params
        if rule.rule_type == "if_then_else":
            for c in p.get("conditions", []):
                col = c.get("column", "")
                if col and col in df.columns and col not in involved:
                    involved.append(col)
        elif rule.rule_type == "formula":
            for token in (p.get("left", ""), p.get("right", "")):
                if token and token in df.columns and token not in involved:
                    involved.append(token)
        elif rule.rule_type == "date_diff":
            for token in (p.get("col_a", ""), p.get("col_b", "")):
                if token and token in df.columns and token not in involved:
                    involved.append(token)

        rows: list[tuple[str, str]] = []
        for i, (idx, result_val) in enumerate(zip(subset.index, new_col_values)):
            if involved:
                parts = [str(subset.loc[idx, c]) for c in involved if c in subset.columns]
                resumen = " | ".join(parts)
            else:
                resumen = f"fila {i + 1}"
            val_str = "" if (isinstance(result_val, float) and np.isnan(result_val)) else str(result_val)
            rows.append((resumen, val_str))

        return rows

    except Exception:
        return []
