"""Migration : recoupe les lignes trop longues des karaoke.json déjà produits.

Utile pour corriger a posteriori les titres passés en niveau 3 (WhisperX), dont
les segments peuvent être de très longues phrases, sans relancer tout le pipeline.

Usage :  python scripts/split_existing_lines.py [--max-words 9]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from karaoke import config
from karaoke.pipeline import _update_index
from karaoke.transcribe import Line, Word, split_long_lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-words", type=int, default=9)
    ap.add_argument("--library", type=Path, default=config.DEFAULT_LIBRARY_DIR)
    args = ap.parse_args()

    changed = 0
    for mf in sorted(args.library.glob("*/karaoke.json")):
        data = json.loads(mf.read_text(encoding="utf-8"))
        lines = [
            Line(l["start"], l["end"],
                 [Word(w["text"], w["start"], w["end"]) for w in l["words"]])
            for l in data.get("lines", [])
        ]
        if not lines:
            continue
        split = split_long_lines(lines, max_words=args.max_words)
        if len(split) == len(lines):
            continue  # rien à découper

        data["lines"] = [
            {"start": round(ln.start, 3), "end": round(ln.end, 3),
             "words": [{"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                       for w in ln.words]}
            for ln in split
        ]
        data["wordLevel"] = any(len(ln.words) > 1 for ln in split)
        mf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✂ {mf.parent.name}: {len(lines)} -> {len(split)} lignes")
        changed += 1

    _update_index(args.library)
    print(f"\n{changed} morceau(x) recoupé(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
