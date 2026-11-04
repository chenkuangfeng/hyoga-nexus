"""Count characters, words and lines of the text passed as JSON on stdin.

Input:  {"text": "..."}   (stdin)
Output: {"characters": int, "words": int, "lines": int}   (stdout)
"""
import json
import sys


def main() -> None:
    args = json.load(sys.stdin)
    text = args["text"]
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
