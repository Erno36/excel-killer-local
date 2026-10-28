"""
engine/recipe.py — Serializacion y persistencia de recetas reutilizables.

Sin imports de PySide6. Solo stdlib + data.models.
RN-019: ningun valor de celda, path de archivo de usuario ni dato personal
        se almacena en la receta ni en los logs que emite este modulo.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from data.models import (
    BusinessRule,
    CleansingRule,
    CrossStepSpec,
    FileEntry,
    FileSpec,
    Recipe,
)


# ---------------------------------------------------------------------------
# Serializacion / deserializacion
# ---------------------------------------------------------------------------

def recipe_to_dict(recipe: Recipe) -> dict:
    """Serializa Recipe a dict JSON-serializable."""
    return {
        "recipe_id": recipe.recipe_id,
        "name": recipe.name,
        "description": recipe.description,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "version": recipe.version,
        "file_specs": [
            {
                "label": fs.label,
                "description": fs.description,
                "expected_columns": list(fs.expected_columns),
            }
            for fs in recipe.file_specs
        ],
        "cleansing_rules": [
            {
                "rule_id": r.rule_id,
                "file_label": r.file_label,
                "column": r.column,
                "operation": r.operation,
                "params": r.params,
            }
            for r in recipe.cleansing_rules
        ],
        "join_type": recipe.join_type,
        "normalize_keys": recipe.normalize_keys,
        "cross_steps": [
            {
                "left_label": step.left_label,
                "right_label": step.right_label,
                "key_pairs": [list(pair) for pair in step.key_pairs],
            }
            for step in recipe.cross_steps
        ],
        "business_rules": [
            {
                "rule_id": r.rule_id,
                "output_column": r.output_column,
                "rule_type": r.rule_type,
                "params": r.params,
            }
            for r in recipe.business_rules
        ],
    }


def recipe_from_dict(d: dict) -> Recipe:
    """
    Deserializa desde dict.
    Lanza ValueError si falta algun campo obligatorio.
    """
    _require(d, ["recipe_id", "name", "version", "file_specs",
                 "cleansing_rules", "join_type", "normalize_keys", "cross_steps"])

    file_specs = [
        FileSpec(
            label=_require_key(fs, "label", "file_specs[].label"),
            description=fs.get("description", ""),
            expected_columns=list(fs.get("expected_columns", [])),
        )
        for fs in d["file_specs"]
    ]

    cleansing_rules = [
        CleansingRule(
            rule_id=_require_key(r, "rule_id", "cleansing_rules[].rule_id"),
            file_label=_require_key(r, "file_label", "cleansing_rules[].file_label"),
            column=_require_key(r, "column", "cleansing_rules[].column"),
            operation=_require_key(r, "operation", "cleansing_rules[].operation"),
            params=r.get("params", {}),
        )
        for r in d["cleansing_rules"]
    ]

    cross_steps = [
        CrossStepSpec(
            left_label=_require_key(s, "left_label", "cross_steps[].left_label"),
            right_label=_require_key(s, "right_label", "cross_steps[].right_label"),
            key_pairs=[tuple(pair) for pair in s.get("key_pairs", [])],
        )
        for s in d["cross_steps"]
    ]

    business_rules = [
        BusinessRule(
            rule_id=_require_key(r, "rule_id", "business_rules[].rule_id"),
            output_column=_require_key(r, "output_column", "business_rules[].output_column"),
            rule_type=_require_key(r, "rule_type", "business_rules[].rule_type"),
            params=r.get("params", {}),
        )
        for r in d.get("business_rules", [])
    ]

    return Recipe(
        recipe_id=d["recipe_id"],
        name=d["name"],
        description=d.get("description", ""),
        created_at=d.get("created_at", _now_iso()),
        updated_at=d.get("updated_at", _now_iso()),
        version=d["version"],
        file_specs=file_specs,
        cleansing_rules=cleansing_rules,
        join_type=d["join_type"],
        normalize_keys=bool(d["normalize_keys"]),
        cross_steps=cross_steps,
        business_rules=business_rules,
    )


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def save_recipe(recipe: Recipe, path: Path) -> None:
    """
    Escribe JSON con indent=2, encoding utf-8.
    Crea directorios intermedios si no existen.
    Solo permite escribir dentro del directorio padre del path (sandbox).
    """
    # Defensa en profundidad: verificar que el path resuelto quede dentro
    # de su propio directorio padre (evita path traversal si el caller
    # construye el path desde datos externos).
    resolved = path.resolve()
    recipes_dir = resolved.parent.resolve()
    if not resolved.is_relative_to(recipes_dir):
        raise ValueError(f"Path fuera del directorio permitido: {path}")
    recipes_dir.mkdir(parents=True, exist_ok=True)
    data = recipe_to_dict(recipe)
    resolved.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_recipe(path: Path) -> Recipe:
    """
    Lee JSON y llama recipe_from_dict.
    Lanza FileNotFoundError si el archivo no existe.
    Lanza ValueError si el contenido es invalido.
    Solo permite leer archivos .json (defensa contra path traversal).
    """
    resolved = path.resolve()
    if resolved.suffix.lower() != ".json":
        raise ValueError(f"Solo se permiten archivos .json: {path.name}")
    if not resolved.exists():
        raise FileNotFoundError(f"Receta no encontrada: {path}")
    text = resolved.read_text(encoding="utf-8")
    try:
        d = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"El archivo no es JSON valido: {exc}") from exc
    return recipe_from_dict(d)


def list_recipes(recipes_dir: Path) -> list[Recipe]:
    """
    Lee todos los *.json del directorio.
    Ignora archivos invalidos sin lanzar excepcion.
    Ordena por updated_at DESC (mas reciente primero).
    """
    if not recipes_dir.exists():
        return []

    recipes: list[Recipe] = []
    for json_file in recipes_dir.glob("*.json"):
        try:
            recipe = load_recipe(json_file)
            recipes.append(recipe)
        except Exception:
            # Archivo corrupto o de otro formato: ignorar silenciosamente.
            pass

    recipes.sort(key=lambda r: r.updated_at, reverse=True)
    return recipes


def delete_recipe(recipe_id: str, recipes_dir: Path) -> bool:
    """
    Elimina el archivo cuyo recipe_id coincida.
    Retorna True si lo encontro y elimino; False si no existia.
    """
    if not recipes_dir.exists():
        return False

    for json_file in recipes_dir.glob("*.json"):
        try:
            d = json.loads(json_file.read_text(encoding="utf-8"))
            if d.get("recipe_id") == recipe_id:
                json_file.unlink()
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Constructor desde estado de la aplicacion
# ---------------------------------------------------------------------------

def build_recipe_from_state(
    name: str,
    description: str,
    file_entries: list[FileEntry],
    cleansing_rules: list[CleansingRule],
    join_type: str,
    normalize_keys: bool,
    cross_steps: list[CrossStepSpec],
    business_rules: list[BusinessRule] | None = None,
) -> Recipe:
    """Constructor de receta desde el estado actual de la app."""
    now = _now_iso()
    file_specs = [
        FileSpec(
            label=entry.label,
            description="",
            expected_columns=list(entry.metadata.column_names),
        )
        for entry in file_entries
    ]
    return Recipe(
        recipe_id=str(uuid.uuid4()),
        name=name,
        description=description,
        created_at=now,
        updated_at=now,
        version="1.0",
        file_specs=file_specs,
        cleansing_rules=list(cleansing_rules),
        join_type=join_type,
        normalize_keys=normalize_keys,
        cross_steps=list(cross_steps),
        business_rules=list(business_rules) if business_rules else [],
    )


# ---------------------------------------------------------------------------
# Validacion
# ---------------------------------------------------------------------------

def validate_recipe_against_entries(
    recipe: Recipe,
    entries: list[FileEntry],
) -> list[str]:
    """
    Retorna lista de advertencias (columnas faltantes, labels sin match).
    Lista vacia = todo OK. No lanza.
    """
    warnings: list[str] = []
    entry_by_label = {e.label: e for e in entries}

    # Verificar que cada FileSpec tenga un FileEntry con el mismo label.
    for spec in recipe.file_specs:
        if spec.label not in entry_by_label:
            warnings.append(
                f"La receta espera un archivo con etiqueta '{spec.label}' "
                f"pero no fue cargado."
            )
            continue
        entry = entry_by_label[spec.label]
        actual_cols = set(entry.metadata.column_names)
        for col in spec.expected_columns:
            if col not in actual_cols:
                warnings.append(
                    f"Columna '{col}' esperada en '{spec.label}' "
                    f"no esta presente en el archivo cargado."
                )

    # Verificar columnas clave de cada paso.
    for step in recipe.cross_steps:
        for col_left, col_right in step.key_pairs:
            left_entry = entry_by_label.get(step.left_label)
            right_entry = entry_by_label.get(step.right_label)
            if left_entry and col_left not in left_entry.metadata.column_names:
                warnings.append(
                    f"Columna clave '{col_left}' de '{step.left_label}' "
                    f"no existe en el archivo cargado."
                )
            if right_entry and col_right not in right_entry.metadata.column_names:
                warnings.append(
                    f"Columna clave '{col_right}' de '{step.right_label}' "
                    f"no existe en el archivo cargado."
                )

    return warnings


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(d: dict, keys: list[str]) -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"Campos obligatorios faltantes en la receta: {missing}")


def _require_key(d: dict, key: str, context: str) -> str:
    if key not in d:
        raise ValueError(f"Campo obligatorio faltante: '{key}' en {context}")
    return d[key]
