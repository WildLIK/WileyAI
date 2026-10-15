"""Run small reproducible Russian checks against the local Ollama server."""
from pathlib import Path
import argparse
import json
import time

import httpx


PROMPTS = [
    ("russian", "Представься на русском как Уайли, личный ассистент. Не более двух предложений."),
    ("command", 'Выдели команду без её выполнения. Верни только JSON с полями action и target. Фраза: «Открой папку загрузок». Возможные action: open_folder, none.'),
    ("negation", 'Определи, нужно ли открывать браузер. Фраза: «Не открывай браузер». Ответь только да или нет.'),
    ("memory", 'Данные владельца: предпочитает короткие ответы и русский язык. Вопрос: как ты будешь отвечать? Одно предложение.'),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--output", default="local/benchmark.json")
    args = parser.parse_args()
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=900, trust_env=False) as http:
        if args.pull:
            last = 0
            with http.stream("POST", "/api/pull", json={"model": args.model}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    item = json.loads(line)
                    if item.get("error"):
                        raise RuntimeError(item["error"])
                    if time.monotonic() - last > 10 or item.get("status") == "success":
                        total = item.get("total", 0)
                        ratio = round(item.get("completed", 0) * 100 / total) if total else 0
                        print(f"{args.model}: {item.get('status')} {ratio}%", flush=True)
                        last = time.monotonic()
        records = []
        for case, prompt in PROMPTS:
            started = time.perf_counter()
            first = None
            answer = ""
            metadata = {}
            with http.stream("POST", "/api/chat", json={"model": args.model, "messages": [{"role": "user", "content": prompt}], "stream": True, "think": False, "keep_alive": "5m", "options": {"num_ctx": 4096, "num_predict": 96, "temperature": 0}}) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    item = json.loads(line)
                    if item.get("error"):
                        raise RuntimeError(item["error"])
                    delta = item.get("message", {}).get("content", "")
                    if delta and first is None:
                        first = time.perf_counter() - started
                    answer += delta
                    if item.get("done"):
                        metadata = item
            record = {"case": case, "answer": answer, "first_token_seconds": round(first or 0, 3), "total_seconds": round(time.perf_counter() - started, 3), "output_tokens": metadata.get("eval_count"), "tokens_per_second": round(metadata.get("eval_count", 0) / max(metadata.get("eval_duration", 1) / 1e9, 0.001), 2)}
            records.append(record)
            print(json.dumps(record, ensure_ascii=False), flush=True)
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"model": args.model, "context": 4096, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
