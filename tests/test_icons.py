"""Every icon the front end asks for must be one tools/vendor.py puts in the build (Lucide is trimmed to that list)."""
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def vendored() -> set[str]:
    """The icons in the built module (tools/vendor.py writes it into the image at build time)."""
    built = Path(os.environ.get("KNWLGE_VENDOR", ROOT / "vendor")) / "lucide" / "icons.js"
    return set(json.loads(built.read_text().split("export default", 1)[1].strip().rstrip(";")))


def test_every_icon_used_is_vendored():
    have = vendored()
    used = set()
    static = ROOT / "app" / "static"
    for f in [p for p in static.rglob("*.js") if p.name != "icons.js"] + [static / "index.html"]:   # icons.js only defines
        text = f.read_text()
        for call in re.findall(r'\bicon\(([^()]*)\)', text):   # icon("x", 16), icon(open ? "x" : "menu", 20)
            used |= {q for q in re.findall(r'"([a-z0-9-]+)"', call) if q != "add"}
        used |= set(re.findall(r'data-icon="([a-z0-9-]+)"', text))
    # names used through lookup tables
    icons_js = (static / "js" / "icons.js").read_text()
    used |= set(re.findall(r':\s*"([a-z0-9-]+)"', icons_js.split("KIND_ICON", 1)[1]))
    course_js = (static / "js" / "views" / "course.js").read_text()
    used |= set(re.findall(r':\s*"([a-z0-9-]+)"', course_js.split("TAB_ICON", 1)[1].split("};", 1)[0]))
    # the section menu's entries carry their icon as the 4th item; the theme button maps themes to icons
    menu = (static / "js" / "sectionmenu.js").read_text()
    used |= set(re.findall(r'entries\.push\(\[.*?, "([a-z0-9-]+)"\]\)', menu))
    main = (static / "js" / "main.js").read_text()
    used |= set(re.findall(r'\["([a-z-]+)", "(?:auto|light|dark)"\]', main))
    assert used, "found no icons at all"
    missing = sorted(used - have)
    assert not missing, f"icons used but not vendored: {missing}"
