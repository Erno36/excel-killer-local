"""
data/models.py — Dataclasses del dominio.

Estas estructuras circulan entre capas; no contienen logica de negocio.
Ningun campo almacena valores de celdas de los Excel (RN-019).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd


# ---------------------------------------------------------------------------
# Motor de reglas de negocio
# ---------------------------------------------------------------------------

@dataclass
class RuleCondition:
    """Una condicion individual dentro de una regla SI/ENTONCES/SINO."""
    column: str
    operator: str   # "==" | "!=" | "<" | "<=" | ">" | ">=" | "contiene" | "es_vacio" | "no_es_vacio"
    value: str = "" # vacio para "es_vacio"/"no_es_vacio"


@dataclass
class BusinessRule:
    """
    Regla de negocio que crea o reemplaza una columna en el resultado del cruce.
    RN-019: output_column es un nombre de campo definido por el usuario, no un valor de celda.
    params no almacena valores de celdas; almacena expresiones de regla.
    """
    rule_id: str
    output_column: str     # nombre de la columna a crear/reemplazar
    rule_type: str         # "if_then_else" | "formula" | "date_diff"
    params: dict = field(default_factory=dict)
    # params segun rule_type:
    # if_then_else: {
    #   "conditions": [{"column":..., "operator":..., "value":...}],
    #   "combinator": "AND" | "OR",
    #   "value_true": str,
    #   "value_false": str
    # }
    # formula: {
    #   "left": str (nombre de columna o literal numerico),
    #   "operator": "+" | "-" | "*" | "/",
    #   "right": str (nombre de columna o literal numerico),
    #   "format": "number" | "text"
    # }
    # date_diff: {
    #   "col_a": str,  # columna de fecha mas reciente (minuendo)
    #   "col_b": str,  # columna de fecha base (sustraendo)
    #   "unit": "days" | "months" | "years",
    #   "absolute": bool
    # }

    @staticmethod
    def new(output_column: str, rule_type: str, params: dict | None = None) -> "BusinessRule":
        import uuid
        return BusinessRule(
            rule_id=str(uuid.uuid4()),
            output_column=output_column,
            rule_type=rule_type,
            params=params or {},
        )


# ---------------------------------------------------------------------------
# Autenticacion
# ---------------------------------------------------------------------------

@dataclass
class User:
    id: int
    username: str
    is_active: bool
    is_test: bool
    created_at: str
    updated_at: str


@dataclass
class LoginAttempt:
    username: str
    attempted_at: str
    success: bool


# ---------------------------------------------------------------------------
# Motor de archivos
# ---------------------------------------------------------------------------

@dataclass
class FileMetadata:
    """Metadatos de un archivo Excel leido. Sin valores de celdas."""
    path: Path | None       # None para archivos virtuales
    sheet_names: list[str]
    sheet_used: str
    row_count: int          # filas de datos (sin encabezado)
    column_names: list[str]
    warnings: list[str] = field(default_factory=list)
    header_row_index: int = 0
    header_candidates: list[int] = field(default_factory=list)
    header_scan_rows: int = 0


@dataclass
class FileEntry:
    """Archivo cargado con su etiqueta y DataFrame en memoria."""
    path: Path | None       # None para archivos virtuales (resultado de cruce previo)
    label: str              # etiqueta libre asignada por el usuario
    sheet_index: int        # -1 = todas las hojas
    df: pd.DataFrame        # datos; NO se serializa ni persiste
    metadata: FileMetadata
    is_virtual: bool = False  # True si proviene de un cruce previo (no de un archivo en disco)


# ---------------------------------------------------------------------------
# Motor de cruce
# ---------------------------------------------------------------------------

@dataclass
class CrossConfig:
    """
    Configuracion completa de un cruce. N >= 2 archivos.

    key_pairs (backward compat): lista plana de N-1 pares, uno por paso.
    steps_key_pairs (nuevo): lista de N-1 listas; cada sub-lista tiene uno
        o mas pares de columnas para ese paso (clave compuesta).

    Si steps_key_pairs esta presente, toma precedencia sobre key_pairs.
    """
    file_entries: list[FileEntry]
    key_pairs: list[tuple[str, str]]                       # backward compat
    join_type: Literal["inner", "left", "outer"]
    normalize_keys: bool                                   # strip + lowercase
    steps_key_pairs: list[list[tuple[str, str]]] = field(default_factory=list)


@dataclass
class CrossResult:
    """Resultado de ejecutar execute_cross(). El DataFrame vive en RAM."""
    df: pd.DataFrame | None     # None en dry_run=True
    row_count: int
    join_type: str
    columns_used: list[str]
    warnings: list[str]
    duration_ms: float
    name: str = ""              # nombre libre asignado por el usuario al cruce
    matched_rows: int | None = None       # filas con match de ambos lados
    left_only_rows: int | None = None     # filas solo en archivo izquierdo (outer/left)
    right_only_rows: int | None = None    # filas solo en archivo derecho (outer)


# ---------------------------------------------------------------------------
# Exportacion
# ---------------------------------------------------------------------------

@dataclass
class ExportOutcome:
    path: Path
    rows_written: int


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """
    Entrada de log de auditoria.
    PROHIBIDO: agregar campos con valores de celdas, CUILes, nombres,
    importes u otros datos personales de los archivos fuente (RN-019).
    """
    timestamp: str
    usuario: str
    accion: str         # LOGIN_OK | LOGIN_FAIL | LOGOUT | FILE_LOAD | COLUMN_DETECT
                        # | CROSS_EXECUTE | EXPORT | ERROR | CLEANSING_APPLY | RULES_APPLY
                        # | STATS_COMPUTED
    # Archivos involucrados: solo nombre y etiqueta, sin contenido.
    archivos: list[dict] = field(default_factory=list)
    columnas: list[str] = field(default_factory=list)
    filas_procesadas: int | None = None
    tipo_join: str | None = None
    duracion_ms: float | None = None
    mensaje_error: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Limpieza de datos
# ---------------------------------------------------------------------------

@dataclass
class CleansingRule:
    """
    Regla de limpieza sobre una columna de un archivo identificado por etiqueta.
    PROHIBIDO: almacenar valores de celdas en ningun campo (RN-019).
    Los params de replace_literal/replace_regex contienen patrones de busqueda,
    no valores extraidos de los datos.
    """
    rule_id: str
    file_label: str
    column: str
    operation: str
    params: dict = field(default_factory=dict)

    @staticmethod
    def new(file_label: str, column: str, operation: str, params: dict | None = None) -> "CleansingRule":
        """Constructor de conveniencia que genera un rule_id automaticamente."""
        import uuid
        return CleansingRule(
            rule_id=str(uuid.uuid4()),
            file_label=file_label,
            column=column,
            operation=operation,
            params=params or {},
        )


# ---------------------------------------------------------------------------
# Recetas reutilizables
# ---------------------------------------------------------------------------

@dataclass
class FileSpec:
    """Descriptor de un archivo esperado en la receta (sin path ni datos)."""
    label: str                            # etiqueta que el usuario debe mapear
    description: str = ""                 # hint legible para el usuario
    expected_columns: list[str] = field(default_factory=list)  # columnas para validacion


@dataclass
class CrossStepSpec:
    """Un paso de cruce entre dos archivos identificados por label."""
    left_label: str
    right_label: str
    key_pairs: list[tuple[str, str]]      # (col_izquierda, col_derecha)


@dataclass
class Recipe:
    """
    Flujo de trabajo completo: que archivos se necesitan, como limpiarlos y como cruzarlos.
    NO contiene paths de archivos ni valores de celdas (RN-019).
    """
    recipe_id: str                        # uuid4
    name: str
    description: str
    created_at: str                       # ISO 8601
    updated_at: str                       # ISO 8601
    version: str                          # "1.0" — para compatibilidad futura
    file_specs: list[FileSpec]            # archivos esperados, en orden
    cleansing_rules: list[CleansingRule]  # reglas de limpieza (serializables)
    join_type: str                        # "inner" | "left" | "outer"
    normalize_keys: bool
    cross_steps: list[CrossStepSpec]      # pasos del cruce por label (no por indice)
    business_rules: list[BusinessRule] = field(default_factory=list)  # reglas de negocio (opcional)
