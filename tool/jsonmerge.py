"""A git merge driver for the Studio's JSON records: jsonmerge.py <base> <ours> <theirs>; the result is written over <ours>.

Two copies of one Studio (the PC's and a server's, for the phone) change different parts of the same file far
more often than the same part. Git's line merge calls that a conflict whenever the changes sit near each other;
this merges by meaning instead. Objects merge key by key, lists of records merge by their "id" (or "key"), other
lists keep what either side added and drop what either side removed. Where both sides changed one value, the
side whose record was "updated" last wins, else theirs. Exit 0 when merged; 1 leaves git's own conflict.
"""
from __future__ import annotations

import json
import sys

GONE = object()


def _ident(item):
    if isinstance(item, dict):
        for key in ("id", "key"):
            if isinstance(item.get(key), str) and item[key]:
                return key, item[key]
    return None


def _list(base, ours, theirs, prefer: str):
    base = base if isinstance(base, list) else []
    if ours and theirs and all(_ident(x) for x in ours + theirs + base):
        b, o, t = ({_ident(x): x for x in side} for side in (base, ours, theirs))
        out = []
        for ident in list(o) + [i for i in t if i not in o]:
            got = merge3(b.get(ident, GONE), o.get(ident, GONE), t.get(ident, GONE), prefer)
            if got is not GONE:
                out.append(got)
        return out
    out = [x for x in ours if x in theirs or x not in base]
    return out + [x for x in theirs if x not in ours and x not in base]


def merge3(base, ours, theirs, prefer: str = "theirs"):
    if ours == theirs:
        return ours
    if base == ours:
        return theirs
    if base == theirs:
        return ours
    if isinstance(ours, dict) and isinstance(theirs, dict):
        if isinstance(ours.get("updated"), str) and isinstance(theirs.get("updated"), str):
            prefer = "ours" if ours["updated"] > theirs["updated"] else "theirs"
        base = base if isinstance(base, dict) else {}
        out = {}
        for key in list(ours) + [k for k in theirs if k not in ours]:
            got = merge3(base.get(key, GONE), ours.get(key, GONE), theirs.get(key, GONE), prefer)
            if got is not GONE:
                out[key] = got
        return out
    if isinstance(ours, list) and isinstance(theirs, list):
        return _list(base, ours, theirs, prefer)
    return ours if prefer == "ours" else theirs


def _read(path: str):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    return json.loads(text) if text.strip() else GONE


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.splitlines()[0], file=sys.stderr)
        return 2
    try:
        base, ours, theirs = (_read(p) for p in argv)
    except (OSError, ValueError) as err:
        print(f"jsonmerge: {err}; leaving the conflict to git", file=sys.stderr)
        return 1
    got = merge3(base, ours, theirs)
    with open(argv[1], "w", encoding="utf-8", newline="\n") as fh:
        if got is not GONE:
            json.dump(got, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
