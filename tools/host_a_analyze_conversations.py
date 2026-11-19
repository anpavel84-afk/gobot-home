"""Read locally saved HOST-A Browser Voice Lab full transcript journals.

This script NEVER contacts network, sends text to cloud, or changes recordings.
Only user-owned Windows PLAN files below the A worktree are read.
"""
from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "run" / "host-a" / "browser-lab" / "conversations"
ALIASES = (
    "моника", "моник", "монки", "модников", "модеников",
    "маньяка", "монитор", "моня",
)


def load(path):
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def inspect(path, *, include_text=True):
    items = load(path)
    by_turn = {}
    frequencies = Counter()
    for event in items:
        turn = event.get("turn", 0)
        if turn > 0:
            by_turn.setdefault(turn, []).append(event)
        if event.get("stage") in {"vosk_partial", "vosk_final"}:
            text = str(event.get("text") or "").lower()
            words = set(re.findall(r"[а-яё]+", text))
            for alias in ALIASES:
                if alias in words:
                    frequencies[alias] += 1
    print(f"Сессия: {path.name}")
    print(f"Всего событий: {len(items)}. Пробуждений: "
          f"{sum(e.get('stage') == 'wake' for e in items)}. "
          f"Завершена: {any(e.get('stage') == 'session_end' for e in items)}")
    print("Появления похожих слов в гипотезах Vosk "
          "(НЕ число отдельных произнесений):", dict(frequencies))
    for turn, entries in sorted(by_turn.items()):
        def single(kind, field):
            matches = [e.get(field) for e in entries
                       if e.get("stage") == kind and e.get(field) is not None]
            return matches[-1] if matches else None
        def visible(s):
            return s if include_text else ("[текст скрыт]" if s else "")
        analysis = [e for e in entries if e.get("stage") ==
                    "turn_analysis" and "latency_ms" in e]
        insight = analysis[-1] if analysis else None
        print(f"  Обращение #{turn}")
        print("    Vosk при пробуждении:",
              visible(single("wake_candidate", "text")))
        print("    OpenAI STT:", visible(single("cloud_final", "text")))
        print("    Статус проверки имени:",
              single("cloud_verdict", "status") or
              single("cloud_rejected", "status"))
        print("    Передано Brain:", visible(single("brain_question", "question")))
        print("    Ответ Brain:", visible(single("brain_final", "text")))
        if insight:
            print("    Статус:", insight.get("status"))
            print("    Времена, мс:", insight.get("latency_ms"))
            print("    На что обратить внимание:", insight.get("findings"))
        else:
            print("    Анализ: ещё не завершён или аварийно прерван")
    return items


def main():
    ap = argparse.ArgumentParser(description="PLAN local full transcript review")
    ap.add_argument("--last", type=int, default=3)
    ap.add_argument("--no-text", action="store_true",
                    help="Only metadata, no conversation words in console")
    args = ap.parse_args()
    if not 1 <= args.last <= 20:
        ap.error("--last must be 1..20")
    paths = sorted(FOLDER.glob("session-*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        print("Полных журналов пока нет: начните новую сессию Browser Voice Lab")
        return
    for path in paths[:args.last]:
        inspect(path, include_text=not args.no_text)
        print()


if __name__ == "__main__":
    main()
