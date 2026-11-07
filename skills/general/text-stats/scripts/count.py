"""Count characters, words and lines of the text on stdin.

Input:  the text, as it is   (stdin)
Output: {"characters": int, "words": int, "lines": int}   (stdout)
"""
import json
import sys


def main() -> None:
    text = sys.stdin.read()
    lines = text.count("\n") + 1 if text else 0
    if text.endswith("\n") and lines > 0:
        lines -= 1
    result = {
        "characters": len(text),
        "words": len(text.split()),
        "lines": lines,
    }
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
