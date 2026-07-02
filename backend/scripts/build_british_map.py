#!/usr/bin/env python3
"""
Build an American-to-British spelling map from the VarCon dataset.

Source: VarCon (Variant Conversion Info) by Kevin Atkinson and Benjamin Titze,
http://wordlist.aspell.net/ . Redistributable with the copyright notice.

Rules:
- Map from the primary American spelling (tag A, not a variant) to the primary
  British spelling (tag B, not a variant). British -ise forms are preferred because
  we read tag B and ignore tag Z (the Oxford -ize British forms).
- Keep only common vocabulary, SCOWL level at or below the threshold.
- Skip possessives, multi-word entries, capitalised proper nouns, and any British
  form with non-ASCII characters.
- Skip a denylist of words whose British spelling depends on meaning (noun vs verb)
  or on software context, so they are never converted automatically. The dictionary
  flag handles those instead.
"""
import json, re, sys

THRESHOLD = 80  # SCOWL level; higher is more obscure. VarCon's own default filters > 80.

DENYLIST = {
    # noun/verb or context dependent, and software-context words
    "license","licenses","licensed","licensing",
    "practice","practices","practiced","practicing",
    "program","programs","programmed","programming","programmer","programmers",
    "meter","meters","metered","metering",
    "disk","disks",
    "tire","tires","tired","tiring",
    "curb","curbs","curbed","curbing",
    "check","checks","checked","checking",
    "story","stories",
    "draft","drafts","drafted","drafting",
    "annex","annexes","annexed","annexing",
    "inquiry","inquiries",
    "judgment","judgments",
    "flier","fliers",
}

def parse_tags(tok):
    # returns (letter, is_variant)
    letter = tok[0]
    rest = tok[1:]
    is_variant = ("v" in rest) or ("V" in rest)
    return letter, is_variant

def main(path):
    level = 50
    out = {}
    level_re = re.compile(r"\(level\s+(\d+)\)")
    with open(path, encoding="latin-1") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.startswith("#"):
                m = level_re.search(line)
                level = int(m.group(1)) if m else 50
                continue
            if level > THRESHOLD:
                continue
            # split off trailing metadata after " | "
            core = line
            meta = ""
            if " | " in line:
                core, meta = line.split(" | ", 1)
                # skip secondary sub-variant lines (:2, :3, ...)
                if re.search(r":\s*([2-9]|\d\d)", meta):
                    continue
            american = None
            british = None
            for pair in core.split(" / "):
                if ":" not in pair:
                    continue
                tagpart, word = pair.split(":", 1)
                word = word.strip()
                if not word or " " in word or "'" in word:
                    continue
                if not re.fullmatch(r"[A-Za-z][A-Za-z-]*", word):
                    continue
                if word[0].isupper():
                    continue
                for tok in tagpart.split():
                    letter, is_variant = parse_tags(tok)
                    if letter == "A" and not is_variant and american is None:
                        american = word
                    if letter == "B" and not is_variant and british is None:
                        british = word
            if not american or not british:
                continue
            if american == british:
                continue
            if american.lower() in DENYLIST:
                continue
            if not british.isascii():
                continue
            out[american.lower()] = british.lower()
    return out

if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "varcon.txt"
    mapping = main(src)
    # stable alphabetical order
    mapping = dict(sorted(mapping.items()))
    print(json.dumps(mapping, ensure_ascii=True, indent=0))
    sys.stderr.write(f"entries: {len(mapping)}\n")
