"""
A component is never declared inside another component's render body.

React reconciles by component *type*. A function defined in a render body is a
new function object every time that body runs, so it is a new type every time —
and React's answer to a changed type is to unmount the whole subtree and mount a
fresh one rather than update it. State inside is discarded, refs are dropped, and
native views are destroyed and recreated.

For a `TextInput` that is not a performance note, it is a broken screen. The
input is controlled by state in the parent, so every keystroke re-renders the
parent, which remounts the input, which dismisses the keyboard and drops focus.
The field accepts exactly one character per tap. Six screens shipped like this,
in all three apps, and they were the six screens where somebody types:

    drop-customer-app  settings/PersonalDetails.tsx   name, phone, floor
    drop-rider-app     Profile.tsx                    name, phone, plate
    drop-rider-app     rider/VehicleDetails.tsx       number plate
    drop-vendor-app    OwnerProfile.tsx               owner name, phone
    drop-vendor-app    StoreProfile.tsx               store name, licence
    drop-vendor-app    business/PayoutSettings.tsx    till, paybill, bank account

The last is the sharpest: a bank account number is up to twelve digits, so
entering one took twelve taps back into the field — precisely the conditions
under which a digit goes in wrong and nobody notices, on the number that decides
where the store's money is paid.

None of this is visible while building a screen. It type-checks, it renders
correctly, and it survives every interaction except typing a second character.

The rule is simply "no component is declared inside another". It was briefly
narrower — only nested components owning a `TextInput` or a hook, on the grounds
that the rest are a re-render cost rather than a defect. That line is real but it
is the wrong place to draw one, for two reasons.

The cost is not nothing. A remount tears down and rebuilds every child, restarts
`PressableScale`'s animation, and asks the reconciler to do its most expensive
kind of work on the most ordinary re-render — on screens that re-render on every
keystroke, every toggle and every query settling.

And the narrow rule cannot hold. The difference between "harmless" and "broken"
is one `TextInput` added to an existing component by somebody who has no reason
to know the enclosing function is where it lives. The nested `InfoRow`s that
dismissed the keyboard did not start out with inputs in them.

So: fourteen more were hoisted after the six that were actually broken, and the
guard now covers the shape rather than the symptom.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = ("drop-customer-app", "drop-rider-app", "drop-vendor-app")

#: What a remount destroys outright, reported first because it is the difference
#: between "slower than it needs to be" and "the keyboard closes on every
#: keystroke". Everything nested is reported either way.
DESTROYED_BY_REMOUNT = (
    re.compile(r"<TextInput\b"),
    re.compile(r"\buseState\s*[(<]"),
    re.compile(r"\buseRef\s*[(<]"),
    re.compile(r"\buseReducer\s*\("),
)

#: A declaration that opens a component: `const Foo = (` / `const Foo = ({` /
#: `function Foo(`. Capitalised, because that is what makes it a component to
#: React rather than a helper. Leading whitespace is required — a declaration at
#: column zero is at module scope, which is the thing we are asking for.
NESTED_DECLARATION = re.compile(
    r"^(?P<indent>[ \t]+)(?:const\s+(?P<const_name>[A-Z]\w*)\s*=\s*(?=[(<]|async\b|function\b)"
    r"|function\s+(?P<fn_name>[A-Z]\w*)\s*\()",
)

pytestmark = pytest.mark.skipif(
    not (REPO / APPS[0]).exists(), reason="apps not in this checkout"
)


def _sources():
    for app in APPS:
        for directory in ("app", "components"):
            root = REPO / app / directory
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.tsx")):
                if "node_modules" in path.parts or "dist" in path.parts:
                    continue
                yield path


def _block(lines: list[str], start: int, indent: str) -> tuple[str, int]:
    """The declaration starting at `start`, up to the first line that closes it.

    Closing is "a line indented no further than the declaration itself, that is
    not blank and not a continuation" — which is what a formatter guarantees here
    and is enough to bound the block. Deliberately simple: the alternative is a
    TypeScript parser, and the cost of over-reading is a false positive that a
    person reads, not a wrong answer that ships.
    """
    body = [lines[start]]
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            body.append(line)
            continue
        leading = line[: len(line) - len(line.lstrip())]
        if len(leading) <= len(indent) and not line.lstrip().startswith(
            (")", "}", "]", ";", ":", "?", "&&", "||", ".", "=>")
        ):
            return "\n".join(body), index
        body.append(line)
    return "\n".join(body), len(lines)


def _nested_components(path: pathlib.Path):
    """Every component declared inside another component in `path`.

    Each is returned with whether it owns something a remount destroys, so the
    failure message can lead with the ones that are actively broken.
    """
    lines = path.read_text(errors="ignore").split("\n")
    found = []
    index = 0
    while index < len(lines):
        match = NESTED_DECLARATION.match(lines[index])
        if not match:
            index += 1
            continue
        name = match.group("const_name") or match.group("fn_name")
        block, end = _block(lines, index, match.group("indent"))
        # A component renders JSX. Without a tag this is a helper — a formatter,
        # a handler, a memoised value — and nesting it is ordinary.
        if "<" not in block or "return" not in block and "=>" not in block:
            index = end
            continue
        if not re.search(r"<[A-Z][A-Za-z0-9]*|<[a-z]+\s|\breturn\s*\(", block):
            index = end
            continue
        destroyed = next(
            (p.pattern for p in DESTROYED_BY_REMOUNT if p.search(block)), None
        )
        found.append((name, index + 1, destroyed))
        index = end
    return found


def test_no_component_is_declared_inside_another_component():
    """The build fails rather than the keyboard closing on somebody's handset."""
    broken, costly = [], []
    for path in _sources():
        for name, line, destroys in _nested_components(path):
            where = f"{path.relative_to(REPO)}:{line}  <{name}>"
            (broken if destroys else costly).append(
                f"{where} — remount destroys {destroys}" if destroys else where
            )

    assert not (broken or costly), (
        "A component declared inside another component is a new type on every "
        "render, so React remounts its whole subtree instead of updating it. "
        "Move it to module scope and pass what it closed over as props.\n\n"
        + ("  BROKEN (loses focus / state on every render):\n    "
           + "\n    ".join(broken) + "\n\n" if broken else "")
        + ("  Remounted needlessly:\n    " + "\n    ".join(costly) if costly else "")
    )


def test_the_scanner_actually_recognises_the_shape_it_is_meant_to_catch():
    """A guard that matches nothing passes for the wrong reason.

    Written against synthetic sources rather than by editing a real screen, so
    the check cannot start depending on a defect staying in the tree.
    """
    import tempfile

    caught = "\n".join([
        "export default function Screen() {",
        "    const [name, setName] = useState('');",
        "    const Field = ({ label }: any) => (",
        "        <View>",
        "            <TextInput value={name} onChangeText={setName} />",
        "        </View>",
        "    );",
        "    return <View><Field label='Name' /></View>;",
        "}",
    ])
    also_caught = "\n".join([
        "export default function Screen() {",
        "    const Counter = () => {",
        "        const [n, setN] = useState(0);",
        "        return <Text>{n}</Text>;",
        "    };",
        "    return <Counter />;",
        "}",
    ])
    allowed_module_scope = "\n".join([
        "const Field = ({ label, value, onChangeText }: any) => (",
        "    <View>",
        "        <TextInput value={value} onChangeText={onChangeText} />",
        "    </View>",
        ");",
        "export default function Screen() {",
        "    const [name, setName] = useState('');",
        "    return <Field value={name} onChangeText={setName} />;",
        "}",
    ])
    nested_no_state = "\n".join([
        "export default function Screen() {",
        "    const Row = ({ label }: any) => <Text>{label}</Text>;",
        "    return <Row label='hello' />;",
        "}",
    ])

    with tempfile.TemporaryDirectory() as directory:
        def scan(source: str):
            path = pathlib.Path(directory) / "Probe.tsx"
            path.write_text(source)
            return _nested_components(path)

        assert scan(caught), "a nested component wrapping a TextInput must be caught"
        assert scan(also_caught), "a nested component holding useState must be caught"
        assert not scan(allowed_module_scope), "a module-scope component must pass"
        # Widened deliberately: a nested component with no input and no state is
        # still a remount, and is one `TextInput` away from being the first case.
        assert scan(nested_no_state), (
            "a nested component must be reported even with no input and no state"
        )
        # A helper that returns no JSX is not a component, and nesting one is
        # ordinary — the guard must not start reporting every local function.
        assert not scan("\n".join([
            "export default function Screen() {",
            "    const formatName = (u: any) => `${u.first} ${u.last}`;",
            "    const total = items.reduce((a, b) => a + b, 0);",
            "    return <Text>{formatName(user)}{total}</Text>;",
            "}",
        ])), "a plain helper function must not be reported"
