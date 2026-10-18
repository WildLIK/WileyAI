import { useEffect, useState } from "react";
import { request, type Alias } from "./api";
import { ProcessStatus } from "./ProcessStatus";

interface FoundApplication {
  id: string;
  name: string;
  category: string;
  target: string;
  source: string;
  aliases: string[];
}
interface ScanResult {
  supported: boolean;
  items: FoundApplication[];
  categories: Record<string, string>;
  warnings: string[];
  scanned_at?: string | null;
}
const key = (name: string) =>
  name.toLocaleLowerCase("ru").replaceAll("ё", "е").trim().replace(/\s+/g, " ");
const pathKey = (path: string) =>
  path.replaceAll("/", "\\").toLocaleLowerCase("ru");

export function Applications({
  aliases,
  onChanged,
  onError,
  disabled = false,
}: {
  aliases: Alias[];
  onChanged(): Promise<void>;
  onError(error: unknown): void;
  disabled?: boolean;
}) {
  const [result, setResult] = useState<ScanResult | null>(null);
  const [category, setCategory] = useState("music");
  const [scanning, setScanning] = useState(false);
  const [adding, setAdding] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void request<ScanResult>(
      "/applications",
      "GET",
      undefined,
      controller.signal,
    )
      .then((saved) => {
        if (
          !controller.signal.aborted &&
          (saved.scanned_at || saved.items.length)
        )
          setResult(saved);
      })
      .catch((error) => {
        if (!controller.signal.aborted) onError(error);
      });
    return () => controller.abort();
  }, []);
  const status = (item: FoundApplication) => {
    const existing = aliases.find(
      (alias) => key(alias.name) === key(item.name),
    );
    if (!existing) return "new";
    return existing.kind === "app" &&
      pathKey(existing.target) === pathKey(item.target)
      ? "added"
      : "conflict";
  };
  const available =
    result?.items.filter((item) => status(item) === "new") || [];
  const scan = async () => {
    setScanning(true);
    setNotice("");
    try {
      const found = await request<ScanResult>("/applications/scan", "POST");
      setResult(found);
      if (!found.items.some((item) => item.category === category))
        setCategory(found.items[0]?.category || "music");
    } catch (error) {
      onError(error);
    } finally {
      setScanning(false);
    }
  };
  const add = async (items: FoundApplication[]) => {
    setAdding(true);
    setNotice("");
    let added = 0;
    const failures: string[] = [];
    try {
      for (const item of items) {
        try {
          await request("/aliases", "POST", {
            name: item.name,
            kind: "app",
            target: item.target,
            replace: false,
          });
          added++;
        } catch (error) {
          failures.push(
            `${item.name}: ${error instanceof Error ? error.message : String(error)}`,
          );
        }
      }
      await onChanged();
      setNotice(
        `Добавлено в команды: ${added}.` +
          (failures.length ? " " + failures.join(" · ") : ""),
      );
    } catch (error) {
      onError(error);
    } finally {
      setAdding(false);
    }
  };
  const locked = disabled || scanning || adding;
  return (
    <section
      className="card application-discovery"
      aria-label="Установленные приложения"
    >
      <div className="application-discovery-heading">
        <div>
          <h2>Приложения на компьютере</h2>
          <p className="help">
            Найдите знакомые программы и добавьте их для запуска голосом или в
            чате.
          </p>
        </div>
        <button
          className="outline"
          disabled={locked}
          onClick={() => void scan()}
        >
          {scanning
            ? "Сканирую…"
            : result?.scanned_at
              ? "Сканировать повторно"
              : "Сканировать приложения"}
        </button>
      </div>
      {!result && !scanning && (
        <p className="help">
          Музыка, видео, графика и рабочие программы, мессенджеры, браузеры и
          стандартные приложения Windows. Сканирование только находит программы;
          запуск доступен после добавления в команды.
        </p>
      )}
      {scanning && (
        <ProcessStatus
          kind="search"
          label="Ищу установленные приложения…"
          detail="Проверяю регистрацию Windows, папки программ и меню «Пуск»"
          compact
        />
      )}
      {result && (
        <>
          <div
            className="application-categories"
            role="group"
            aria-label="Категории приложений"
          >
            {Object.entries(result.categories).map(([id, name]) => (
              <button
                type="button"
                key={id}
                aria-pressed={id === category}
                onClick={() => setCategory(id)}
              >
                {name}{" "}
                <small>
                  {result.items.filter((item) => item.category === id).length}
                </small>
              </button>
            ))}
          </div>
          <div
            className="application-results"
            aria-label={result.categories[category]}
          >
            {result.items
              .filter((item) => item.category === category)
              .map((item) => (
                <article
                  className="found-application"
                  key={item.id}
                  aria-label={item.name}
                >
                  <div className="found-application-heading">
                    <strong>{item.name}</strong>
                    <button
                      className="outline"
                      disabled={locked || status(item) !== "new"}
                      onClick={() => void add([item])}
                    >
                      {status(item) === "added"
                        ? "Добавлено"
                        : status(item) === "conflict"
                          ? "Имя занято"
                          : "Добавить"}
                    </button>
                  </div>
                  <code className="application-path">{item.target}</code>
                  <small>{item.source}</small>
                  <span className="application-example">
                    «Открой {item.aliases[0] || item.name}»
                  </span>
                </article>
              ))}
            {!result.items.some((item) => item.category === category) && (
              <p className="help">
                В этой категории ничего не найдено. Приложение можно добавить
                вручную через EXE или ярлык ниже.
              </p>
            )}
          </div>
          <div className="application-discovery-footer">
            <span className="help">
              Найдено: {result.items.length}. Ваши существующие команды
              сохраняются.
              {result.scanned_at && (
                <>
                  {" "}
                  Последний поиск:{" "}
                  {new Date(result.scanned_at).toLocaleString("ru-RU")}. Список
                  сохранён.
                </>
              )}
            </span>
            <button
              className="outline"
              disabled={locked || !available.length}
              onClick={() => void add(available)}
            >
              Добавить все найденные · {available.length}
            </button>
          </div>
          {result.warnings.map((warning) => (
            <p className="help" key={warning}>
              {warning}
            </p>
          ))}
        </>
      )}
      {notice && (
        <p className="application-import-result" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
