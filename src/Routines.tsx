import { useCallback, useEffect, useMemo, useState } from "react";
import { request, scopedRequest } from "./api";

type Step = { kind: string; label: string; target: string };
type Routine = { id: string; name: string; steps: Step[] };
type Access = {
  allow_file_open: boolean;
  allow_app_open: boolean;
  allow_web_open: boolean;
  allow_audio_control: boolean;
  command_understanding: boolean;
};
type ToolInfo = {
  access: Omit<Access, "command_understanding">;
  command_understanding: boolean;
  choices: Step[];
};
const kinds: Record<string, string> = {
  folder: "Папка",
  file: "Файл",
  app: "Приложение",
  url: "Сайт",
};

export function ToolAccess({
  onError,
  onSaved,
}: {
  onError: (error: unknown) => void;
  onSaved: () => Promise<void>;
}) {
  const [access, setAccess] = useState<Access>();
  const [working, setWorking] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const load = () =>
      void request<ToolInfo>("/tools")
        .then((data) =>
          setAccess({
            ...data.access,
            command_understanding: data.command_understanding,
          }),
        )
        .catch(onError);
    load();
    const channel = new BroadcastChannel("wiley-ui");
    channel.onmessage = (event) => {
      if (event.data.type === "settings") load();
    };
    return () => channel.close();
  }, []);
  if (!access) return null;
  return (
    <div className="card" aria-label="Доступ к инструментам">
      <h2>Доступ к инструментам</h2>
      <p className="help">
        Действует для команд, сценариев и открытия поисковых источников во всех
        окнах.
      </p>
      {(
        [
          ["allow_file_open", "Открывать файлы и папки"],
          ["allow_app_open", "Запускать приложения"],
          ["allow_web_open", "Открывать сайты"],
          ["allow_audio_control", "Управлять звуком и медиаклавишами Windows"],
        ] as const
      ).map(([field, label]) => (
        <label className="checkbox" key={field}>
          <input
            type="checkbox"
            checked={access[field]}
            disabled={working}
            onChange={(event) => {
              setAccess({ ...access, [field]: event.target.checked });
              setSaved(false);
            }}
          />
          {label}
        </label>
      ))}
      <label className="checkbox">
        <input
          type="checkbox"
          checked={access.command_understanding}
          disabled={working}
          onChange={(event) => {
            setAccess({
              ...access,
              command_understanding: event.target.checked,
            });
            setSaved(false);
          }}
        />
        Понимать свободные команды с помощью модели
      </label>
      <p className="help">
        Если точная команда не найдена, выбранная модель получит вашу фразу и
        названия доступных команд. Она предложит варианты из каталога; для
        открытия ответьте «да» или номером. История, память и документы в этот
        разбор не добавляются. Предложение действует 5 минут.
      </p>
      <div className="button-row">
        <button
          className="outline"
          disabled={working}
          onClick={async () => {
            setWorking(true);
            try {
              await request("/tools/access", "PUT", access);
              await onSaved();
              setSaved(true);
            } catch (error) {
              onError(error);
            } finally {
              setWorking(false);
            }
          }}
        >
          Сохранить доступ
        </button>
        {saved && <small role="status">Доступ сохранён</small>}
      </div>
      <p className="help">
        Поиск в интернете включается отдельно в настройках поиска.
      </p>
    </div>
  );
}

export function RoutinePanel({
  conversationId,
  scopeName,
  aliasesVersion,
  disabled,
  onRun,
  onError,
}: {
  conversationId: string;
  scopeName: string;
  aliasesVersion: string;
  disabled: boolean;
  onRun: (text: string) => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const scoped = useMemo(() => scopedRequest(conversationId), [conversationId]);
  const [items, setItems] = useState<Routine[]>([]);
  const [choices, setChoices] = useState<Step[]>([]);
  const [choice, setChoice] = useState("");
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<Step[]>([]);
  const [editing, setEditing] = useState<string>();
  const [deleting, setDeleting] = useState<string>();
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");
  const load = useCallback(async () => {
    const [routines, tools] = await Promise.all([
      scoped<Routine[]>("/routines"),
      request<ToolInfo>("/tools"),
    ]);
    setItems(routines);
    setChoices(tools.choices);
  }, [scoped]);
  useEffect(() => {
    void load().catch(onError);
  }, [load, aliasesVersion]);
  useEffect(() => {
    const channel = new BroadcastChannel("wiley-ui");
    channel.onmessage = (event) => {
      if (event.data.type === "routines-changed") void load().catch(onError);
    };
    return () => channel.close();
  }, [load]);
  const locked = disabled || working;
  const selectedChoice = choices.find(
    (item) => JSON.stringify(item) === choice,
  );
  function reset() {
    setEditing(undefined);
    setName("");
    setSteps([]);
    setChoice("");
  }
  async function run(action: () => Promise<void>) {
    setWorking(true);
    setNotice("");
    try {
      await action();
    } catch (error) {
      onError(error);
    } finally {
      setWorking(false);
    }
  }
  function notify() {
    const channel = new BroadcastChannel("wiley-ui");
    channel.postMessage({ type: "routines-changed" });
    channel.close();
  }
  function change(index: number, value: Partial<Step>) {
    setSteps((items) =>
      items.map((item, i) => (i === index ? { ...item, ...value } : item)),
    );
  }
  function move(index: number, delta: number) {
    setSteps((items) => {
      const result = [...items];
      [result[index], result[index + delta]] = [
        result[index + delta],
        result[index],
      ];
      return result;
    });
  }
  return (
    <div className="routine-section" aria-label="Сценарии запуска">
      <div className="card">
        <h2>Сценарии запуска</h2>
        <span className="scope-label">
          {scopeName.replace("Память", "Пространство")}
        </span>
        <p>Сохраните набор открытий и скажите: «Запусти сценарий Работа».</p>
        <p className="help">
          Шаги выполняются по порядку. Перед запуском проверяются все пути и
          доступ. Команда открытия передаётся Windows; готовность окон не
          ожидается. «Стоп» останавливает оставшиеся шаги.
        </p>
        {items.map((item) => (
          <article className="routine-entry" key={item.id}>
            <h3>{item.name}</h3>
            <ol>
              {item.steps.map((step, index) => (
                <li key={index}>
                  <strong>{step.label}</strong>
                  <small>
                    {kinds[step.kind]} · {step.target}
                  </small>
                </li>
              ))}
            </ol>
            <div className="button-row">
              <button
                className="primary"
                disabled={locked}
                onClick={() => void onRun("Запусти сценарий " + item.name)}
              >
                Запустить {item.name}
              </button>
              <button
                className="outline"
                disabled={locked}
                onClick={() =>
                  void run(async () => {
                    const data = await scoped<{ text: string }>(
                      "/routines/" + item.id + "/check",
                      "POST",
                    );
                    setNotice(data.text);
                  })
                }
              >
                Проверить {item.name}
              </button>
              <button
                className="subtle"
                disabled={locked}
                onClick={() => {
                  setEditing(item.id);
                  setName(item.name);
                  setSteps(item.steps.map((step) => ({ ...step })));
                  setNotice("");
                }}
              >
                Изменить {item.name}
              </button>
              <button
                className="subtle danger"
                disabled={locked}
                onClick={() => setDeleting(item.id)}
              >
                Удалить {item.name}
              </button>
            </div>
            {deleting === item.id && (
              <div
                className="button-row"
                role="group"
                aria-label="Подтверждение удаления сценария"
              >
                <button
                  className="subtle danger"
                  disabled={locked}
                  onClick={() =>
                    void run(async () => {
                      await scoped("/routines/" + item.id, "DELETE");
                      setDeleting(undefined);
                      if (editing === item.id) reset();
                      await load();
                      notify();
                    })
                  }
                >
                  Удалить сценарий навсегда
                </button>
                <button
                  className="subtle"
                  onClick={() => setDeleting(undefined)}
                >
                  Отмена удаления
                </button>
              </div>
            )}
          </article>
        ))}
        {!items.length && (
          <p className="help">В этом пространстве ещё нет сценариев.</p>
        )}
        {notice && <p role="status">{notice}</p>}
      </div>
      <form
        className="card"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await scoped(
              editing ? "/routines/" + editing : "/routines",
              editing ? "PUT" : "POST",
              { name, steps },
            );
            reset();
            await load();
            notify();
            setNotice("Сценарий сохранён");
          });
        }}
      >
        <h2>{editing ? "Изменить сценарий" : "Новый сценарий"}</h2>
        <label>
          Название сценария
          <input
            maxLength={80}
            required
            value={name}
            disabled={locked}
            placeholder="Работа"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        {steps.map((step, index) => (
          <fieldset className="routine-step" key={index} disabled={locked}>
            <legend>Шаг {index + 1}</legend>
            <div className="two-columns">
              <label>
                Тип шага {index + 1}
                <select
                  aria-label={"Тип шага " + (index + 1)}
                  value={step.kind}
                  onChange={(event) =>
                    change(index, { kind: event.target.value })
                  }
                >
                  {Object.entries(kinds).map(([kind, label]) => (
                    <option key={kind} value={kind}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Название шага {index + 1}
                <input
                  aria-label={"Название шага " + (index + 1)}
                  required
                  maxLength={150}
                  value={step.label}
                  onChange={(event) =>
                    change(index, { label: event.target.value })
                  }
                />
              </label>
            </div>
            <label>
              Путь или адрес шага {index + 1}
              <div className="input-with-button">
                <input
                  aria-label={"Путь или адрес шага " + (index + 1)}
                  required
                  maxLength={4096}
                  value={step.target}
                  onChange={(event) =>
                    change(index, { target: event.target.value })
                  }
                />
                {step.kind !== "url" && (
                  <button
                    type="button"
                    className="outline"
                    onClick={() =>
                      void run(async () => {
                        const path = await window.wiley.pickFile(step.kind);
                        if (path) change(index, { target: path });
                      })
                    }
                  >
                    Обзор шага {index + 1}
                  </button>
                )}
              </div>
            </label>
            <div className="button-row">
              <button
                type="button"
                className="subtle"
                disabled={locked || index === 0}
                aria-label={"Шаг " + (index + 1) + " выше"}
                onClick={() => move(index, -1)}
              >
                ↑ Выше
              </button>
              <button
                type="button"
                className="subtle"
                disabled={locked || index === steps.length - 1}
                aria-label={"Шаг " + (index + 1) + " ниже"}
                onClick={() => move(index, 1)}
              >
                ↓ Ниже
              </button>
              <button
                type="button"
                className="subtle danger"
                aria-label={"Убрать шаг " + (index + 1)}
                onClick={() =>
                  setSteps((items) => items.filter((_, i) => i !== index))
                }
              >
                Убрать
              </button>
            </div>
          </fieldset>
        ))}
        <div className="routine-add">
          <label>
            Готовое действие
            <select
              aria-label="Готовое действие"
              value={choice}
              disabled={locked}
              onChange={(event) => setChoice(event.target.value)}
            >
              <option value="">Выберите действие…</option>
              {choices.map((item) => (
                <option
                  key={item.kind + item.target}
                  value={JSON.stringify(item)}
                >
                  {kinds[item.kind]} · {item.label}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="outline"
            disabled={locked || !selectedChoice || steps.length >= 12}
            onClick={() => {
              if (selectedChoice) setSteps([...steps, { ...selectedChoice }]);
              setChoice("");
            }}
          >
            Добавить шаг
          </button>
          <button
            type="button"
            className="subtle"
            disabled={locked || steps.length >= 12}
            onClick={() =>
              setSteps([...steps, { kind: "folder", label: "", target: "" }])
            }
          >
            Добавить свой шаг
          </button>
        </div>
        <p className="help">
          До 12 шагов. Сценарий хранит собственные пути: изменение команды в
          каталоге не меняет уже сохранённый сценарий.
        </p>
        <div className="button-row">
          <button
            className="primary"
            disabled={locked || !name.trim() || !steps.length}
          >
            Сохранить сценарий
          </button>
          {editing && (
            <button
              type="button"
              className="subtle"
              disabled={locked}
              onClick={reset}
            >
              Отменить изменение
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
