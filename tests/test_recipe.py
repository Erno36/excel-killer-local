"""
tests/test_recipe.py — Pruebas unitarias para engine/recipe.py.

Cubre: serializacion, deserializacion, persistencia, listado, eliminacion,
build_recipe_from_state y validate_recipe_against_entries.
Sin dependencias de PySide6.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from data.models import (
    CleansingRule,
    CrossStepSpec,
    FileEntry,
    FileMetadata,
    FileSpec,
    Recipe,
)
from engine.recipe import (
    build_recipe_from_state,
    delete_recipe,
    list_recipes,
    load_recipe,
    recipe_from_dict,
    recipe_to_dict,
    save_recipe,
    validate_recipe_against_entries,
)

import pandas as pd


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_recipe(**overrides) -> Recipe:
    """Construye una Recipe minima valida para usar en tests."""
    base = dict(
        recipe_id="test-uuid-001",
        name="Receta de prueba",
        description="Descripcion de prueba",
        created_at="2026-10-26T00:00:00+00:00",
        updated_at="2026-10-26T00:00:00+00:00",
        version="1.0",
        file_specs=[
            FileSpec(label="Stock", description="Archivo de stock", expected_columns=["CUIL", "Importe"]),
            FileSpec(label="Bajas", description="", expected_columns=["CUIL"]),
        ],
        cleansing_rules=[
            CleansingRule(
                rule_id="rule-001",
                file_label="Stock",
                column="CUIL",
                operation="remove_chars",
                params={"chars": "-."},
            )
        ],
        join_type="inner",
        normalize_keys=True,
        cross_steps=[
            CrossStepSpec(
                left_label="Stock",
                right_label="Bajas",
                key_pairs=[("CUIL", "CUIL")],
            )
        ],
    )
    base.update(overrides)
    return Recipe(**base)


def make_file_entry(label: str, columns: list[str]) -> FileEntry:
    df = pd.DataFrame({col: ["a", "b"] for col in columns})
    metadata = FileMetadata(
        path=None,
        sheet_names=[],
        sheet_used="Hoja1",
        row_count=2,
        column_names=columns,
    )
    return FileEntry(path=None, label=label, sheet_index=0, df=df, metadata=metadata)


# ---------------------------------------------------------------------------
# Serializacion
# ---------------------------------------------------------------------------

class TestRecipeToDict:
    def test_round_trip(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        restored = recipe_from_dict(d)
        assert restored.recipe_id == recipe.recipe_id
        assert restored.name == recipe.name
        assert restored.join_type == recipe.join_type
        assert restored.normalize_keys == recipe.normalize_keys

    def test_file_specs_preserved(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        assert len(d["file_specs"]) == 2
        assert d["file_specs"][0]["label"] == "Stock"
        assert d["file_specs"][0]["expected_columns"] == ["CUIL", "Importe"]

    def test_cleansing_rules_preserved(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        assert len(d["cleansing_rules"]) == 1
        rule = d["cleansing_rules"][0]
        assert rule["operation"] == "remove_chars"
        assert rule["params"] == {"chars": "-."}

    def test_cross_steps_preserved(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        assert len(d["cross_steps"]) == 1
        step = d["cross_steps"][0]
        assert step["left_label"] == "Stock"
        assert step["key_pairs"] == [["CUIL", "CUIL"]]

    def test_json_serializable(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        # No debe lanzar al serializar a JSON.
        text = json.dumps(d)
        assert "recipe_id" in text


class TestRecipeFromDict:
    def test_missing_required_field_raises_value_error(self):
        d = recipe_to_dict(make_recipe())
        del d["recipe_id"]
        with pytest.raises(ValueError, match="recipe_id"):
            recipe_from_dict(d)

    def test_missing_name_raises(self):
        d = recipe_to_dict(make_recipe())
        del d["name"]
        with pytest.raises(ValueError):
            recipe_from_dict(d)

    def test_optional_description_defaults_to_empty(self):
        d = recipe_to_dict(make_recipe())
        del d["description"]
        recipe = recipe_from_dict(d)
        assert recipe.description == ""

    def test_key_pairs_converted_to_tuples(self):
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        restored = recipe_from_dict(d)
        pair = restored.cross_steps[0].key_pairs[0]
        assert isinstance(pair, tuple)
        assert pair == ("CUIL", "CUIL")

    def test_normalize_keys_bool(self):
        d = recipe_to_dict(make_recipe(normalize_keys=False))
        restored = recipe_from_dict(d)
        assert restored.normalize_keys is False


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

class TestSaveLoadRecipe:
    def test_save_creates_file(self, tmp_path):
        recipe = make_recipe()
        dest = tmp_path / "receta.json"
        save_recipe(recipe, dest)
        assert dest.exists()

    def test_save_creates_parent_dirs(self, tmp_path):
        recipe = make_recipe()
        dest = tmp_path / "subdir" / "nested" / "receta.json"
        save_recipe(recipe, dest)
        assert dest.exists()

    def test_load_roundtrip(self, tmp_path):
        recipe = make_recipe()
        dest = tmp_path / "receta.json"
        save_recipe(recipe, dest)
        loaded = load_recipe(dest)
        assert loaded.recipe_id == recipe.recipe_id
        assert loaded.name == recipe.name

    def test_load_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_recipe(tmp_path / "no_existe.json")

    def test_load_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("esto no es json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_recipe(bad_file)

    def test_load_json_missing_field(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text(json.dumps({"name": "solo nombre"}), encoding="utf-8")
        with pytest.raises(ValueError):
            load_recipe(bad_file)

    def test_utf8_encoding(self, tmp_path):
        recipe = make_recipe(name="Receta de Seguros — Ñoño")
        dest = tmp_path / "receta.json"
        save_recipe(recipe, dest)
        loaded = load_recipe(dest)
        assert loaded.name == "Receta de Seguros — Ñoño"


class TestListRecipes:
    def test_empty_dir(self, tmp_path):
        result = list_recipes(tmp_path)
        assert result == []

    def test_nonexistent_dir(self, tmp_path):
        result = list_recipes(tmp_path / "no_existe")
        assert result == []

    def test_lists_all_valid(self, tmp_path):
        r1 = make_recipe(recipe_id="id-1", name="A", updated_at="2026-01-01T00:00:00+00:00")
        r2 = make_recipe(recipe_id="id-2", name="B", updated_at="2026-06-01T00:00:00+00:00")
        save_recipe(r1, tmp_path / "id-1.json")
        save_recipe(r2, tmp_path / "id-2.json")
        result = list_recipes(tmp_path)
        assert len(result) == 2

    def test_sorted_desc_by_updated_at(self, tmp_path):
        r1 = make_recipe(recipe_id="id-1", name="Antigua", updated_at="2025-01-01T00:00:00+00:00")
        r2 = make_recipe(recipe_id="id-2", name="Reciente", updated_at="2026-10-01T00:00:00+00:00")
        save_recipe(r1, tmp_path / "id-1.json")
        save_recipe(r2, tmp_path / "id-2.json")
        result = list_recipes(tmp_path)
        assert result[0].name == "Reciente"

    def test_ignores_invalid_json_files(self, tmp_path):
        valid = make_recipe(recipe_id="id-ok", name="Valida")
        save_recipe(valid, tmp_path / "id-ok.json")
        (tmp_path / "corrupto.json").write_text("no es json", encoding="utf-8")
        result = list_recipes(tmp_path)
        assert len(result) == 1
        assert result[0].name == "Valida"

    def test_ignores_non_json_files(self, tmp_path):
        (tmp_path / "notas.txt").write_text("algo", encoding="utf-8")
        result = list_recipes(tmp_path)
        assert result == []


class TestDeleteRecipe:
    def test_delete_existing(self, tmp_path):
        recipe = make_recipe(recipe_id="delete-me")
        save_recipe(recipe, tmp_path / "delete-me.json")
        result = delete_recipe("delete-me", tmp_path)
        assert result is True
        assert not (tmp_path / "delete-me.json").exists()

    def test_delete_nonexistent_returns_false(self, tmp_path):
        result = delete_recipe("no-existe", tmp_path)
        assert result is False

    def test_delete_nonexistent_dir(self, tmp_path):
        result = delete_recipe("id", tmp_path / "no_existe")
        assert result is False

    def test_delete_does_not_remove_other_recipes(self, tmp_path):
        r1 = make_recipe(recipe_id="keep-me", name="Mantener")
        r2 = make_recipe(recipe_id="delete-me", name="Eliminar")
        save_recipe(r1, tmp_path / "keep-me.json")
        save_recipe(r2, tmp_path / "delete-me.json")
        delete_recipe("delete-me", tmp_path)
        remaining = list_recipes(tmp_path)
        assert len(remaining) == 1
        assert remaining[0].recipe_id == "keep-me"


# ---------------------------------------------------------------------------
# build_recipe_from_state
# ---------------------------------------------------------------------------

class TestBuildRecipeFromState:
    def test_creates_recipe_with_correct_name(self):
        entries = [make_file_entry("Stock", ["CUIL"]), make_file_entry("Bajas", ["CUIL"])]
        step = CrossStepSpec(left_label="Stock", right_label="Bajas", key_pairs=[("CUIL", "CUIL")])
        recipe = build_recipe_from_state(
            name="Mi receta",
            description="Descripcion",
            file_entries=entries,
            cleansing_rules=[],
            join_type="inner",
            normalize_keys=True,
            cross_steps=[step],
        )
        assert recipe.name == "Mi receta"
        assert recipe.version == "1.0"

    def test_file_specs_built_from_entries(self):
        entries = [make_file_entry("Stock", ["CUIL", "Importe"])]
        recipe = build_recipe_from_state(
            name="X", description="", file_entries=entries,
            cleansing_rules=[], join_type="outer", normalize_keys=False, cross_steps=[],
        )
        assert len(recipe.file_specs) == 1
        assert recipe.file_specs[0].label == "Stock"
        assert "CUIL" in recipe.file_specs[0].expected_columns

    def test_cleansing_rules_copied(self):
        entries = [make_file_entry("A", ["col"])]
        rule = CleansingRule.new("A", "col", "strip_spaces")
        recipe = build_recipe_from_state(
            name="X", description="", file_entries=entries,
            cleansing_rules=[rule], join_type="inner", normalize_keys=True, cross_steps=[],
        )
        assert len(recipe.cleansing_rules) == 1
        assert recipe.cleansing_rules[0].operation == "strip_spaces"

    def test_recipe_id_is_unique(self):
        entries = [make_file_entry("A", ["x"])]
        r1 = build_recipe_from_state("A", "", entries, [], "inner", True, [])
        r2 = build_recipe_from_state("B", "", entries, [], "inner", True, [])
        assert r1.recipe_id != r2.recipe_id

    def test_no_paths_stored(self):
        """RN-019: la receta no debe contener paths de archivos."""
        entries = [make_file_entry("A", ["x"]), make_file_entry("B", ["x"])]
        recipe = build_recipe_from_state("X", "", entries, [], "inner", True, [])
        d = recipe_to_dict(recipe)
        text = json.dumps(d)
        # Los FileSpec no tienen campo path
        assert "path" not in text


# ---------------------------------------------------------------------------
# validate_recipe_against_entries
# ---------------------------------------------------------------------------

class TestValidateRecipeAgainstEntries:
    def test_valid_entries_no_warnings(self):
        recipe = make_recipe()
        entries = [
            make_file_entry("Stock", ["CUIL", "Importe"]),
            make_file_entry("Bajas", ["CUIL"]),
        ]
        warnings = validate_recipe_against_entries(recipe, entries)
        assert warnings == []

    def test_missing_label_generates_warning(self):
        recipe = make_recipe()
        entries = [make_file_entry("Stock", ["CUIL", "Importe"])]
        # "Bajas" no esta cargado.
        warnings = validate_recipe_against_entries(recipe, entries)
        assert any("Bajas" in w for w in warnings)

    def test_missing_column_generates_warning(self):
        recipe = make_recipe()
        entries = [
            make_file_entry("Stock", ["CUIL"]),  # falta "Importe"
            make_file_entry("Bajas", ["CUIL"]),
        ]
        warnings = validate_recipe_against_entries(recipe, entries)
        assert any("Importe" in w for w in warnings)

    def test_missing_key_column_in_cross_step(self):
        recipe = make_recipe()
        entries = [
            make_file_entry("Stock", ["OtraClave"]),  # falta "CUIL" para el cruce
            make_file_entry("Bajas", ["CUIL"]),
        ]
        warnings = validate_recipe_against_entries(recipe, entries)
        assert any("CUIL" in w for w in warnings)

    def test_no_entries_all_warn(self):
        recipe = make_recipe()
        warnings = validate_recipe_against_entries(recipe, [])
        assert len(warnings) >= 2  # Stock y Bajas no cargados

    def test_returns_list_not_raises(self):
        """validate nunca lanza; siempre retorna lista."""
        recipe = make_recipe()
        result = validate_recipe_against_entries(recipe, [])
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Seguridad: RN-019 y path traversal
# ---------------------------------------------------------------------------

class TestRN019RecipeNoPaths:
    """Verifica que recipe_to_dict no filtre paths de archivos ni datos de celdas."""

    def test_recipe_to_dict_no_contiene_path_de_archivo(self, tmp_path):
        """
        RN-019: si los FileEntry tienen paths reales, esos paths NO deben
        aparecer en el dict serializado de la receta.
        """
        path_sensible = tmp_path / "datos_secretos" / "clientes_julio.xlsx"
        meta = FileMetadata(
            path=path_sensible,
            sheet_names=["Hoja1"],
            sheet_used="Hoja1",
            row_count=10,
            column_names=["CUIL", "Importe"],
        )
        entry = FileEntry(
            path=path_sensible,
            label="Stock",
            sheet_index=0,
            df=pd.DataFrame({"CUIL": ["20-11111111-1"], "Importe": [1500]}),
            metadata=meta,
        )
        recipe = build_recipe_from_state(
            name="Receta segura",
            description="",
            file_entries=[entry],
            cleansing_rules=[],
            join_type="inner",
            normalize_keys=True,
            cross_steps=[],
        )
        d = recipe_to_dict(recipe)
        text = json.dumps(d)
        assert "datos_secretos" not in text, "Path de directorio sensible no debe aparecer"
        assert "clientes_julio" not in text, "Nombre de archivo sensible no debe aparecer"
        assert str(path_sensible) not in text, "Path completo no debe aparecer en JSON"

    def test_recipe_to_dict_no_contiene_valores_de_celdas(self):
        """
        RN-019: la receta solo almacena nombres de columnas, no valores.
        Los expected_columns son strings de nombres, no valores de datos.
        """
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        text = json.dumps(d)
        # Valores de celdas ficticios que NO deben aparecer
        assert "20-11111111-1" not in text
        assert "Juan Perez" not in text
        assert "1500.00" not in text

    def test_recipe_no_tiene_campo_path(self):
        """
        RN-019: el dict de receta no debe tener ningun campo llamado 'path'.
        FileSpec no tiene campo path por diseno.
        """
        recipe = make_recipe()
        d = recipe_to_dict(recipe)
        text = json.dumps(d)
        # 'path' como clave JSON no debe existir en ninguna parte del dict
        assert '"path"' not in text, "No debe existir clave 'path' en el JSON de receta"

    def test_audit_recipe_save_no_contiene_paths(self, tmp_path):
        """
        RN-019: la entrada de auditoria RECIPE_SAVE no debe contener paths
        de archivos del usuario.
        """
        from audit.logger import AuditLogger, make_timestamp
        from data.models import AuditEntry

        log_dir = tmp_path / ".logs"
        logger = AuditLogger(log_dir)

        path_usuario = "/home/coordinadora/documentos/seguros_junio.xlsx"
        logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario="coordinadora",
            accion="RECIPE_SAVE",
            extra={
                "recipe_name": "Seguros mensual",
                "file_specs_count": 1,
                "rules_count": 0,
                "cross_steps_count": 1,
                "join_type": "inner",
                # RN-019: NO se debe incluir el path del archivo del usuario
            },
        ))

        log_files = list(log_dir.glob("*.jsonl"))
        assert log_files, "Debe haberse creado al menos un archivo de log"
        content = log_files[0].read_text(encoding="utf-8")
        assert path_usuario not in content, (
            "El log de RECIPE_SAVE no debe contener paths de archivos del usuario"
        )
        assert "seguros_junio.xlsx" not in content, (
            "El nombre del archivo fuente no debe aparecer en el log"
        )

    def test_audit_recipe_load_no_contiene_paths(self, tmp_path):
        """
        RN-019: la entrada de auditoria RECIPE_LOAD no debe contener paths
        de archivos del usuario.
        """
        from audit.logger import AuditLogger, make_timestamp
        from data.models import AuditEntry

        log_dir = tmp_path / ".logs"
        logger = AuditLogger(log_dir)

        path_usuario = "C:\\Users\\coordinadora\\Documentos\\anticipos_julio.xlsx"
        logger.log(AuditEntry(
            timestamp=make_timestamp(),
            usuario="coordinadora",
            accion="RECIPE_LOAD",
            extra={
                "recipe_name": "Anticipos mensual",
                "files_mapped": 2,
                "warnings_count": 0,
                # RN-019: NO se debe incluir el path del archivo del usuario
            },
        ))

        log_files = list(log_dir.glob("*.jsonl"))
        assert log_files
        content = log_files[0].read_text(encoding="utf-8")
        assert path_usuario not in content
        assert "anticipos_julio.xlsx" not in content


class TestPathTraversalRecipe:
    """
    Verifica que las funciones de persistencia de recetas no permitan
    escrituras o lecturas fuera del directorio de recetas cuando se
    usan paths esperados en el flujo normal.
    """

    def test_save_recipe_uuid_id_queda_dentro_de_recipes_dir(self, tmp_path):
        """
        En el flujo normal, recipe_id es un UUID generado por build_recipe_from_state.
        La ruta resultante debe quedar dentro del directorio de recetas.
        """
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        recipe = build_recipe_from_state(
            name="Test",
            description="",
            file_entries=[make_file_entry("A", ["col1"])],
            cleansing_rules=[],
            join_type="inner",
            normalize_keys=True,
            cross_steps=[],
        )
        dest = recipes_dir / f"{recipe.recipe_id}.json"
        # UUID no contiene '..' ni separadores de path
        assert ".." not in recipe.recipe_id
        assert "/" not in recipe.recipe_id
        assert "\\" not in recipe.recipe_id
        # El path destino debe ser un hijo directo de recipes_dir
        assert dest.parent.resolve() == recipes_dir.resolve()
        save_recipe(recipe, dest)
        assert dest.exists()

    def test_load_recipe_path_traversal_lanza_file_not_found(self, tmp_path):
        """
        Un path con traversal (../../etc/passwd.json) que no existe debe
        lanzar FileNotFoundError, no un error de sistema ni datos inesperados.
        """
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()
        malicious_path = recipes_dir / "../../etc/passwd.json"
        with pytest.raises(FileNotFoundError):
            load_recipe(malicious_path)

    def test_delete_recipe_no_elimina_archivos_fuera_del_directorio(self, tmp_path):
        """
        delete_recipe itera glob('*.json') dentro de recipes_dir.
        Aunque el recipe_id coincida con un path externo, solo puede
        eliminar archivos encontrados por glob (todos dentro del directorio).
        """
        recipes_dir = tmp_path / "recipes"
        recipes_dir.mkdir()

        # Archivo externo que NO debe ser eliminado
        archivo_externo = tmp_path / "archivo_externo.txt"
        archivo_externo.write_text("contenido importante", encoding="utf-8")

        # Crear receta con recipe_id que intenta apuntar a un archivo externo
        import json
        trick_json = recipes_dir / "trick.json"
        trick_json.write_text(
            json.dumps({
                "recipe_id": str(archivo_externo),  # path absoluto como id
                "name": "trick",
            }),
            encoding="utf-8",
        )

        # delete_recipe borra el archivo dentro de recipes_dir, no el archivo externo
        result = delete_recipe(str(archivo_externo), recipes_dir)
        assert result is True, "Debe retornar True (encontro el archivo con ese recipe_id)"
        assert not trick_json.exists(), "El archivo dentro de recipes_dir debe ser eliminado"
        assert archivo_externo.exists(), (
            "El archivo externo NO debe ser eliminado, "
            "ya que delete_recipe solo trabaja dentro de recipes_dir"
        )
