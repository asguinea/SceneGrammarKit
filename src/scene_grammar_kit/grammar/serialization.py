"""Deterministic JSON serialization and safe persistence for grammars."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scene_grammar_kit.grammar.errors import (
    GrammarFileExistsError,
    GrammarFileNotFoundError,
    GrammarJSONError,
    GrammarReadError,
    GrammarSerializationError,
    GrammarValidationError,
    GrammarWriteError,
)
from scene_grammar_kit.grammar.models import (
    Axis,
    Bounds3D,
    GeometryType,
    GrammarNode,
    RepeatNode,
    SceneGrammar,
    SplitChild,
    SplitNode,
    TerminalNode,
    Vector3,
)


def grammar_to_canonical_json(grammar: SceneGrammar) -> str:
    """Serialize a grammar to deterministic, compact JSON.

    Canonical output uses UTF-8-compatible Unicode text, lexicographically
    sorted object keys, preserved list/child order, compact separators, no
    indentation, no NaN or infinity, and no final newline. These are project
    rules and do not claim conformance to an external canonical-JSON standard.
    """
    if not isinstance(grammar, SceneGrammar):
        raise GrammarSerializationError("grammar must be a SceneGrammar")
    try:
        return json.dumps(
            _grammar_to_data(grammar),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise GrammarSerializationError(
            f"Could not serialize grammar canonically: {exc}"
        ) from exc


def grammar_from_json(text: str) -> SceneGrammar:
    """Parse JSON text into a strict :class:`SceneGrammar`."""
    if not isinstance(text, str):
        raise GrammarJSONError("Grammar JSON input must be text")
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GrammarJSONError(f"Invalid grammar JSON: {exc}") from exc
    return _parse_scene_grammar(data)


def load_grammar(path: Path) -> SceneGrammar:
    """Load and validate a UTF-8 grammar file."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise GrammarFileNotFoundError(f"Grammar file does not exist: {resolved}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GrammarReadError(
            f"Could not read grammar file as UTF-8: {resolved}: {exc}"
        ) from exc
    return grammar_from_json(text)


def save_grammar(
    grammar: SceneGrammar,
    path: Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> Path:
    """Atomically save canonical UTF-8 JSON and return its resolved path.

    Parent directories are created only with ``create_parents=True``. Existing
    files are preserved unless ``overwrite=True``. A temporary file in the
    destination directory prevents partial target files after failed writes.
    """
    canonical_text = grammar_to_canonical_json(grammar)
    resolved = Path(path).expanduser().resolve()
    parent = resolved.parent

    if create_parents:
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise GrammarWriteError(
                f"Could not create grammar parent directory {parent}: {exc}"
            ) from exc
    if not parent.is_dir():
        raise GrammarWriteError(
            f"Grammar parent directory does not exist: {parent}; "
            "pass create_parents=True to create it"
        )
    if resolved.exists() and not overwrite:
        raise GrammarFileExistsError(
            f"Grammar file already exists; pass overwrite=True to replace it: "
            f"{resolved}"
        )

    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(canonical_text)
            stream.flush()
            os.fsync(stream.fileno())

        if overwrite:
            os.replace(temporary_path, resolved)
        else:
            try:
                os.link(temporary_path, resolved)
            except FileExistsError as exc:
                raise GrammarFileExistsError(
                    "Grammar file appeared during save and was not overwritten: "
                    f"{resolved}"
                ) from exc
            temporary_path.unlink()
        temporary_path = None
    except GrammarFileExistsError:
        raise
    except OSError as exc:
        raise GrammarWriteError(
            f"Could not safely write grammar file {resolved}: {exc}"
        ) from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    return resolved


def _grammar_to_data(grammar: SceneGrammar) -> dict[str, Any]:
    """Convert a typed grammar to JSON-compatible values."""
    return {
        "schema_version": grammar.schema_version,
        "scene_id": grammar.scene_id,
        "units": grammar.units,
        "root_bounds": {
            "min": list(grammar.root_bounds.minimum.as_tuple()),
            "max": list(grammar.root_bounds.maximum.as_tuple()),
        },
        "root": _node_to_data(grammar.root),
    }


def _node_to_data(node: GrammarNode) -> dict[str, Any]:
    """Convert one recursive node to its tagged persisted representation."""
    if isinstance(node, TerminalNode):
        data: dict[str, Any] = {
            "node_id": node.node_id,
            "type": node.type,
            "semantic_class": node.semantic_class,
            "geometry": node.geometry.value,
        }
        if node.attributes:
            data["attributes"] = dict(node.attributes)
        return data
    if isinstance(node, RepeatNode):
        return {
            "node_id": node.node_id,
            "type": node.type,
            "axis": node.axis.value,
            "count": node.count,
            "spacing": node.spacing,
            "element": _node_to_data(node.element),
        }
    if isinstance(node, SplitNode):
        return {
            "node_id": node.node_id,
            "type": node.type,
            "axis": node.axis.value,
            "children": [
                {"weight": child.weight, "node": _node_to_data(child.node)}
                for child in node.children
            ],
        }
    raise GrammarSerializationError(
        f"Unsupported grammar node class: {type(node).__name__}"
    )


def _parse_scene_grammar(value: object) -> SceneGrammar:
    """Parse and strictly validate the root grammar object."""
    data = _object(value, "$")
    _exact_fields(
        data,
        required={"schema_version", "scene_id", "units", "root_bounds", "root"},
        optional=set(),
        path="$",
    )
    bounds_data = _object(data["root_bounds"], "$.root_bounds")
    _exact_fields(
        bounds_data,
        required={"min", "max"},
        optional=set(),
        path="$.root_bounds",
    )
    try:
        return SceneGrammar(
            schema_version=_string(data["schema_version"], "$.schema_version"),
            scene_id=_string(data["scene_id"], "$.scene_id"),
            units=_string(data["units"], "$.units"),
            root_bounds=Bounds3D(
                minimum=_vector(bounds_data["min"], "$.root_bounds.min"),
                maximum=_vector(bounds_data["max"], "$.root_bounds.max"),
            ),
            root=_parse_node(data["root"], "$.root"),
        )
    except GrammarValidationError as exc:
        raise GrammarValidationError(f"Grammar validation failed: {exc}") from exc


def _parse_node(value: object, path: str) -> GrammarNode:
    """Parse a recursive tagged node union."""
    data = _object(value, path)
    if "type" not in data:
        raise GrammarValidationError(f"{path}.type is required")
    node_type = _string(data["type"], f"{path}.type")
    if node_type == "terminal":
        return _parse_terminal(data, path)
    if node_type == "repeat":
        return _parse_repeat(data, path)
    if node_type == "split":
        return _parse_split(data, path)
    raise GrammarValidationError(
        f"{path}.type has unknown node type {node_type!r}; "
        "expected split, repeat, or terminal"
    )


def _parse_terminal(data: Mapping[str, object], path: str) -> TerminalNode:
    """Parse a strict terminal node."""
    _exact_fields(
        data,
        required={"node_id", "type", "semantic_class", "geometry"},
        optional={"attributes"},
        path=path,
    )
    geometry_text = _string(data["geometry"], f"{path}.geometry")
    try:
        geometry = GeometryType(geometry_text)
    except ValueError as exc:
        raise GrammarValidationError(
            f"{path}.geometry must be one of: box, plane, empty"
        ) from exc
    attributes_value = data.get("attributes", {})
    attributes = _attributes(attributes_value, f"{path}.attributes")
    return TerminalNode(
        node_id=_string(data["node_id"], f"{path}.node_id"),
        semantic_class=_string(data["semantic_class"], f"{path}.semantic_class"),
        geometry=geometry,
        attributes=attributes,
    )


def _parse_repeat(data: Mapping[str, object], path: str) -> RepeatNode:
    """Parse a strict repeat node without performing repeat-fit validation."""
    _exact_fields(
        data,
        required={"node_id", "type", "axis", "count", "spacing", "element"},
        optional=set(),
        path=path,
    )
    return RepeatNode(
        node_id=_string(data["node_id"], f"{path}.node_id"),
        axis=_parse_axis(data["axis"], f"{path}.axis"),
        count=_integer(data["count"], f"{path}.count"),
        spacing=_number(data["spacing"], f"{path}.spacing"),
        element=_parse_node(data["element"], f"{path}.element"),
    )


def _parse_split(data: Mapping[str, object], path: str) -> SplitNode:
    """Parse a strict ordered split node."""
    _exact_fields(
        data,
        required={"node_id", "type", "axis", "children"},
        optional=set(),
        path=path,
    )
    children_data = _array(data["children"], f"{path}.children")
    children: list[SplitChild] = []
    for index, value in enumerate(children_data):
        child_path = f"{path}.children[{index}]"
        child_data = _object(value, child_path)
        _exact_fields(
            child_data,
            required={"weight", "node"},
            optional=set(),
            path=child_path,
        )
        children.append(
            SplitChild(
                weight=_number(child_data["weight"], f"{child_path}.weight"),
                node=_parse_node(child_data["node"], f"{child_path}.node"),
            )
        )
    return SplitNode(
        node_id=_string(data["node_id"], f"{path}.node_id"),
        axis=_parse_axis(data["axis"], f"{path}.axis"),
        children=tuple(children),
    )


def _parse_axis(value: object, path: str) -> Axis:
    """Parse one of the three exact axis strings."""
    text = _string(value, path)
    try:
        return Axis(text)
    except ValueError as exc:
        raise GrammarValidationError(f"{path} must be one of: x, y, z") from exc


def _vector(value: object, path: str) -> Vector3:
    """Parse an exact three-number coordinate array."""
    values = _array(value, path)
    if len(values) != 3:
        raise GrammarValidationError(f"{path} must contain exactly 3 numbers")
    return Vector3(
        _number(values[0], f"{path}[0]"),
        _number(values[1], f"{path}[1]"),
        _number(values[2], f"{path}[2]"),
    )


def _attributes(value: object, path: str) -> dict[str, str | int | float]:
    """Parse optional scalar/string terminal attributes without coercion."""
    data = _object(value, path)
    parsed: dict[str, str | int | float] = {}
    for key, item in data.items():
        if not key:
            raise GrammarValidationError(f"{path} keys must be nonempty strings")
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            raise GrammarValidationError(
                f"{path}.{key} must be a string, integer, or finite number"
            )
        if isinstance(item, float) and not _is_finite(item):
            raise GrammarValidationError(f"{path}.{key} must be finite")
        parsed[key] = item
    return parsed


def _object(value: object, path: str) -> Mapping[str, object]:
    """Require a JSON object with string keys."""
    if not isinstance(value, dict):
        raise GrammarValidationError(f"{path} must be an object")
    return value


def _array(value: object, path: str) -> Sequence[object]:
    """Require a JSON array rather than another sequence type."""
    if not isinstance(value, list):
        raise GrammarValidationError(f"{path} must be an array")
    return value


def _string(value: object, path: str) -> str:
    """Require a JSON string without coercion."""
    if not isinstance(value, str):
        raise GrammarValidationError(f"{path} must be a string")
    return value


def _integer(value: object, path: str) -> int:
    """Require a JSON integer without accepting booleans or floats."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise GrammarValidationError(f"{path} must be an integer")
    return value


def _number(value: object, path: str) -> float:
    """Require a finite JSON number without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GrammarValidationError(f"{path} must be a number")
    normalized = float(value)
    if not _is_finite(normalized):
        raise GrammarValidationError(f"{path} must be finite")
    return normalized


def _exact_fields(
    data: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
    path: str,
) -> None:
    """Reject missing and unexpected object fields."""
    missing = sorted(required - data.keys())
    if missing:
        raise GrammarValidationError(
            f"{path} missing required field(s): {', '.join(missing)}"
        )
    unexpected = sorted(data.keys() - required - optional)
    if unexpected:
        raise GrammarValidationError(
            f"{path} has unexpected field(s): {', '.join(unexpected)}"
        )


def _reject_json_constant(value: str) -> None:
    """Reject the non-standard JSON constants NaN and infinity."""
    raise ValueError(f"non-finite constant {value!r} is not permitted")


def _is_finite(value: float) -> bool:
    """Return whether a float is neither NaN nor infinite."""
    return value == value and value not in (float("inf"), float("-inf"))
