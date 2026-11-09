"""samples/*.json → out/<이름>/ (DOCX·PDF·PNG·점검결과.json)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nomudocs.generate import generate  # noqa: E402

root = Path(__file__).resolve().parent
for f in sorted((root / "samples").glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    out = generate(data, root / "out" / f.stem, stem=f.stem)
    lv = [x["level"] for x in out["report"]["findings"]]
    print(f"{f.stem}: png={len(out.get('png', []))} findings={ {k: lv.count(k) for k in set(lv)} }")
