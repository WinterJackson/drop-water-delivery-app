"""Every relationship a response schema serialises must be eager-loaded.

## Why this cannot be a behavioural test

`tests/conftest.py` yields an `AsyncMock()` for the session: **no test in this
suite touches a real database**, so no test exercises the ORM's loading at all.
A missing eager load is therefore invisible to every other file here, and would
first appear as a 500 on a real request against a real Postgres.

That also corrects a claim worth stating plainly: adding `lazy="raise_on_sql"`
does *not* move these failures into the test run. Under asyncio an unloaded
attribute already raised — `MissingGreenlet`, from deep inside SQLAlchemy, naming
a greenlet rather than the relationship. What the setting buys is a clear error
that names the attribute, and a declaration that lazy loading is not a strategy
this codebase uses. What *finds* the defect is this file.

## What it checks

Pydantic reads every declared field during serialisation. So a response schema
with a field named after a relationship is a hard requirement on the query that
produced the row: load it, or take an exception per row on a real database.

The check walks from the schema to the route that returns it, to the service
function the route delegates to, and asserts the eager load is there. It found
two real gaps when it was written, both of which worked only by accident:

* `get_deliverer_orders` never loaded `Order.deliverer`, and got away with it
  because `get_deliverer_by_clerk_id` runs first and puts that rider in the
  session's identity map, where a many-to-one lookup finds it without SQL. Every
  order in that result belongs to that one rider, so every lookup hit.
* `get_trip_radar_orders` never loaded it either, and got away with it because an
  `unassigned` order usually has a null `deliverer_id` — and a many-to-one with a
  null foreign key resolves to `None` without touching the database. A re-offered
  order is unassigned *with* a rider still on the row.

Neither is the kind of thing a reviewer spots, and neither would fail until the
platform had the traffic to produce the case.
"""
import ast
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent

EAGER_LOADERS = ("selectinload", "joinedload", "subqueryload", "contains_eager", "immediateload")
_EAGER_RE = re.compile(r"(?:%s)\(\s*\w+\.(\w+)" % "|".join(EAGER_LOADERS))


def _relationship_names() -> dict[str, set[str]]:
    """`{model class: {relationship attribute, ...}}`, read from the models."""
    by_class: dict[str, set[str]] = {}
    for path in (BACKEND / "models").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = {
                target.id
                for stmt in node.body
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                and getattr(stmt.value.func, "id", "") == "relationship"
                for target in stmt.targets
                if isinstance(target, ast.Name)
            }
            if names:
                by_class[node.name] = names
    return by_class


def _functions(folder: str) -> dict[str, tuple[pathlib.Path, str]]:
    """`{function name: (path, source)}` for one package."""
    out: dict[str, tuple[pathlib.Path, str]] = {}
    for path in (BACKEND / folder).rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.setdefault(node.name, (path, ast.get_source_segment(source, node) or ""))
    return out


def test_every_relationship_declares_a_loading_strategy():
    """No relationship may fall back to the library default.

    A bare `backref="name"` is the trap: `lazy=` on the declaration governs only
    the forward direction, so the reverse side keeps `lazy="select"` with nothing
    at the call site to show it. Two of the platform's 38 were in exactly that
    state, both collections, on the two rows most likely to be held across a
    long-running request.
    """
    from sqlalchemy.orm import configure_mappers

    import models.bottle_rejection_model  # noqa: F401
    import models.cart_model  # noqa: F401
    import models.deliverer_model  # noqa: F401
    import models.favorites_model  # noqa: F401
    import models.order_model  # noqa: F401
    import models.product_model  # noqa: F401
    import models.saved_location_model  # noqa: F401
    import models.user_model  # noqa: F401
    import models.vendor_favorite_model  # noqa: F401
    import models.vendor_model  # noqa: F401
    import models.vendor_rider_model  # noqa: F401
    import models.vendor_staff_model  # noqa: F401
    from db.session import Base

    configure_mappers()

    offenders = [
        f"{mapper.class_.__name__}.{rel.key} (lazy={rel.lazy!r})"
        for mapper in Base.registry.mappers
        for rel in mapper.relationships
        if rel.lazy != "raise_on_sql"
    ]
    assert offenders == [], (
        "these relationships still lazy-load; under asyncio that is an exception "
        f"per row on a real database: {offenders}"
    )


def _schema_relationship_fields() -> dict[str, set[str]]:
    """`{response schema: {relationship field, ...}}`, following inheritance.

    A field only counts when its annotation names another model — `deliverer_id:
    UUID` is a column and `deliverer: Optional[OrderDelivererSnippet]` is a load.
    """
    relationships = set().union(*_relationship_names().values())
    declared: dict[str, tuple[set[str], list[str]]] = {}

    for path in (BACKEND / "schemas").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            fields = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id in relationships
                and re.search(r"[A-Z]", ast.unparse(stmt.annotation))
            }
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            # Composition counts as well as inheritance. A page envelope
            # (`data: list[ProductFull]`) serialises everything `ProductFull`
            # does, but its own field is called `data`, which is not the name of
            # any relationship — so following bases alone drops it and the route
            # returning it is never checked at all. That is how three product
            # listings could name a schema carrying `vendor` and go unexamined.
            composed = [
                referenced
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                for referenced in re.findall(r"\b([A-Z]\w+)\b", ast.unparse(stmt.annotation))
            ]
            declared[node.name] = (fields, bases + composed)

    def resolved(name: str, seen: frozenset = frozenset()) -> set[str]:
        if name not in declared or name in seen:
            return set()
        own, related = declared[name]
        inherited: set[str] = set()
        for other in related:
            inherited |= resolved(other, seen | {name})
        return own | inherited

    return {name: resolved(name) for name in declared if resolved(name)}


def test_every_serialised_relationship_is_eager_loaded():
    """Walk schema → route → service and require the load at the end of it."""
    schema_fields = _schema_relationship_fields()
    assert schema_fields, "no response schema declares a relationship field; the parser has broken"

    route_sources = _functions("routes")
    service_sources = _functions("services")

    offenders = []
    checked = 0

    for path in (BACKEND / "routes").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text()
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = " ".join(ast.unparse(d) for d in node.decorator_list)
            match = re.search(r"response_model\s*=\s*([\w\[\]\| .]+)", decorators)
            if not match:
                continue
            required: set[str] = set()
            for schema, fields in schema_fields.items():
                if re.search(rf"\b{re.escape(schema)}\b", match.group(1)):
                    required |= fields
            if not required:
                continue

            body = ast.get_source_segment(source, node) or ""
            loaded = set(_EAGER_RE.findall(body))

            # The route delegates, and so does the service. Following a single
            # level found the load only when the query was written inline in the
            # service function; the moment three listings shared one query
            # builder, the `contains_eager` sat one level further down and the
            # guard reported a route that was correct. Follow the chain instead,
            # bounded so a cycle cannot hang the suite.
            def _bodies(source_text: str, depth: int, seen: frozenset) -> set[str]:
                found = set(_EAGER_RE.findall(source_text))
                if depth <= 0:
                    return found
                try:
                    inner = ast.parse(source_text)
                except SyntaxError:
                    return found
                for call in ast.walk(inner):
                    if not isinstance(call, ast.Call):
                        continue
                    called = (
                        call.func.attr if isinstance(call.func, ast.Attribute)
                        else getattr(call.func, "id", "")
                    )
                    if not called or called in seen:
                        continue
                    table = service_sources if called in service_sources else route_sources
                    if called in table:
                        found |= _bodies(table[called][1], depth - 1, seen | {called})
                return found

            loaded |= _bodies(body, 3, frozenset({node.name}))

            checked += 1
            missing = required - loaded
            if missing:
                offenders.append(
                    f"{path.relative_to(BACKEND)}:{node.lineno} {node.name}() "
                    f"serialises {sorted(missing)} without loading it"
                )

    assert checked >= 8, (
        f"only {checked} serialising routes were found; the response_model scan has "
        "stopped matching and this test is passing vacuously"
    )
    assert offenders == [], offenders
