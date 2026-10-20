import { useEffect, useMemo, useState } from "react";
import { scopedRequest } from "./api";
type Contact = {
  id: string;
  name: string;
  email: string;
  phone: string;
  telegram: string;
  notes: string;
  updated: string;
};
const blank = () => ({
  name: "",
  email: "",
  phone: "",
  telegram: "",
  notes: "",
});
export function ContactsPanel({ conversationId }: { conversationId: string }) {
  const request = useMemo(
    () => scopedRequest(conversationId),
    [conversationId],
  );
  const [items, setItems] = useState<Contact[]>([]),
    [selected, setSelected] = useState<Contact | null>(null),
    [editor, setEditor] = useState(blank),
    [query, setQuery] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const load = async () =>
    setItems(
      await request<Contact[]>("/contacts?query=" + encodeURIComponent(query)),
    );
  useEffect(() => {
    let live = true;
    void request<Contact[]>("/contacts?query=" + encodeURIComponent(query))
      .then((value) => {
        if (live) setItems(value);
      })
      .catch((err) => {
        if (live) setError(String(err));
      });
    return () => {
      live = false;
    };
  }, [request, query]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="page scroll-page">
      <h1>Контакты</h1>
      <p>
        Адресная книга текущего пространства. Контакты можно выбирать при
        подготовке письма.
      </p>
      {error && <p role="alert">{error}</p>}
      <div className="mail-grid">
        <div className="card">
          <label>
            Найти контакт
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={200}
            />
          </label>
          <button
            className="outline"
            onClick={() => {
              setSelected(null);
              setEditor(blank());
            }}
          >
            Новый контакт
          </button>
          <div className="mail-items">
            {items.map((item) => (
              <button
                className="mail-item"
                key={item.id}
                onClick={() => {
                  setSelected(item);
                  setEditor({
                    name: item.name,
                    email: item.email,
                    phone: item.phone,
                    telegram: item.telegram,
                    notes: item.notes,
                  });
                }}
              >
                <strong>{item.name}</strong>
                <span>{item.email}</span>
                <small>
                  {item.phone} {item.telegram}
                </small>
              </button>
            ))}
          </div>
        </div>
        <form
          className="card"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              const value = await request<Contact>(
                "/contacts" +
                  (selected
                    ? "/" +
                      selected.id +
                      "?expected_updated=" +
                      encodeURIComponent(selected.updated)
                    : ""),
                selected ? "PUT" : "POST",
                editor,
              );
              setSelected(value);
            });
          }}
        >
          <h2>{selected ? "Изменить контакт" : "Новый контакт"}</h2>
          <fieldset disabled={busy}>
            {(
              [
                ["name", "Имя"],
                ["email", "Email"],
                ["phone", "Телефон"],
                ["telegram", "Telegram"],
                ["notes", "Примечание"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  required={key === "name"}
                  value={editor[key]}
                  onChange={(event) =>
                    setEditor({ ...editor, [key]: event.target.value })
                  }
                  maxLength={
                    key === "notes"
                      ? 2000
                      : key === "email"
                        ? 254
                        : key === "phone"
                          ? 50
                          : key === "telegram"
                            ? 100
                            : 160
                  }
                />
              </label>
            ))}
            <div className="button-row">
              <button className="primary">Сохранить контакт</button>
              {selected && (
                <button
                  type="button"
                  className="subtle danger"
                  onClick={() =>
                    void run(async () => {
                      await request(
                        "/contacts/" +
                          selected.id +
                          "?expected_updated=" +
                          encodeURIComponent(selected.updated),
                        "DELETE",
                      );
                      setSelected(null);
                      setEditor(blank());
                    })
                  }
                >
                  Удалить контакт
                </button>
              )}
            </div>
          </fieldset>
        </form>
      </div>
    </section>
  );
}
