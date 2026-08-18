"""Every model is registered, so `Base.metadata` describes the whole schema.

`models/__init__.py` is what makes a mapper known. Import a model module and its
table joins `Base.metadata`; leave it out and the table is reachable only by the
services that happen to import it directly — which they do, so nothing fails and
nothing says anything.

Four models sat in that state: `Bottle_Rejection_Tickets`,
`Customer_First_Delivery`, `Deliverer_Vendors` and `failed_webhooks`. Two
consequences, both silent:

* **`Base.metadata` was not the schema.** Building a database from the models
  produced 28 tables where the deployed one has 32. The admin console's analytics
  and nav-count endpoints then answered 500 with
  `relation "Bottle_Rejection_Tickets" does not exist` — on a database that had
  just been reported as successfully created.
* **Every guard that reflects over the models skipped them.**
  `test_sql_type_safety.py` walks `Base.metadata` so that a column which becomes
  an enum later is covered without anybody remembering to add it. Three of the
  four carry enum columns, and it had never looked at any of them — the precise
  blind spot that let `COALESCE(vendor_business_type, varchar)` reach customers.

`Customer_First_Delivery` is the one that shows why this is not bookkeeping: it
is the materialised acquisition cohort, written on the delivery path and read by
the growth report, and it was absent from the platform's own description of
itself.
"""

import ast
import pathlib

import pytest

MODELS_DIR = pathlib.Path(__file__).resolve().parent.parent / "models"


def _model_modules_defining_a_table() -> set[str]:
    """Every `models/*_model.py` that declares a `__tablename__`, by module stem."""
    modules = set()
    for path in sorted(MODELS_DIR.glob("*_model.py")):
        if "__tablename__" in path.read_text(encoding="utf-8"):
            modules.add(path.stem)
    return modules


def _modules_imported_by_the_package() -> set[str]:
    """The module stems `models/__init__.py` imports, read from its source.

    Static on purpose. Measuring this at runtime cannot work: `conftest.py`
    imports `main`, which imports the routes, which import services, which import
    several model modules *directly* — so by the time any test runs, those
    tables are in `Base.metadata` whether or not the package ever asked for them.
    Two earlier versions of this file measured `Base.metadata` and passed against
    the exact commit they were written to catch, for that reason.

    The source of `models/__init__.py` is the only thing that states the
    intended registry independently of what else happened to get imported.
    """
    source = (MODELS_DIR / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            imported.add(node.module)
    return imported


def test_every_model_module_is_imported_by_the_package():
    """A model file that `models/__init__.py` does not import is a table the
    platform does not know it has."""
    defining = _model_modules_defining_a_table()
    imported = _modules_imported_by_the_package()

    missing = sorted(defining - imported)

    assert not missing, (
        "These model modules declare a table and are not imported by "
        "`models/__init__.py`, so their tables are absent from `Base.metadata` — "
        "a database built from the models will not have them, and every guard "
        "that reflects over the models silently skips them:\n  "
        + "\n  ".join(f"models/{module}.py" for module in missing)
    )


def test_the_registry_is_not_empty():
    """Non-vacuity, both ways.

    If `models/__init__.py` stopped importing anything the test above would
    compare a full set against an empty one and fail loudly — but if the *glob*
    ever stopped matching, it would compare two empty sets and pass in silence.
    """
    defining = _model_modules_defining_a_table()
    imported = _modules_imported_by_the_package()

    assert len(defining) >= 25, (
        f"Only {len(defining)} model modules found under {MODELS_DIR}. The glob "
        "has stopped matching, and the test above is now vacuous."
    )
    assert len(imported) >= 25, (
        f"`models/__init__.py` imports only {len(imported)} modules."
    )


@pytest.mark.parametrize(
    "module",
    [
        "bottle_rejection_model",
        "customer_cohort_model",
        "deliverer_vendor_model",
        "failed_webhook_model",
    ],
)
def test_the_four_that_were_missing_stay_registered(module: str):
    """Named individually, because these four are the regression.

    `Customer_First_Delivery` in particular: the materialised acquisition cohort
    that `services/customer_cohort_service.py` writes on every delivery and the
    growth report reads. Absent from the metadata, it was absent from any
    database built out of it.
    """
    assert module in _modules_imported_by_the_package(), (
        f"`models/{module}.py` is no longer imported by `models/__init__.py`."
    )
