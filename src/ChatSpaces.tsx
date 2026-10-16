import { useEffect, useRef, useState } from "react";
import { request, type Chat, type Project } from "./api";

export function ChatSpaces({
  chats,
  projects,
  active,
  disabled,
  onSelect,
  onChanged,
  onError,
}: {
  chats: Chat[];
  projects: Project[];
  active: string;
  disabled: boolean;
  onSelect: (id: string) => Promise<void>;
  onChanged: (id?: string) => Promise<void>;
  onError: (error: unknown) => void;
}) {
  const [editor, setEditor] = useState<{
    kind: "chat" | "project";
    id?: string;
    name: string;
    project_id: string;
    deleting?: boolean;
  } | null>(null);
  const [working, setWorking] = useState(false);
  const [filter, setFilter] = useState("");
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    if (editor)
      dialog.current
        ?.querySelector<HTMLElement>("input,select,button")
        ?.focus();
  }, [editor?.kind, editor?.id, editor?.deleting]);
  async function run(action: () => Promise<void>) {
    setWorking(true);
    try {
      await action();
    } catch (error) {
      onError(error);
    } finally {
      setWorking(false);
    }
  }
  async function create(projectId: string | null = null) {
    await run(async () => {
      const chat = await request<Chat>("/conversations", "POST", {
        project_id: projectId,
      });
      await onChanged(chat.id);
    });
  }
  async function save() {
    if (!editor) return;
    await run(async () => {
      const route = editor.kind === "chat" ? "/conversations" : "/projects";
      const result = await request<Chat & Project>(
        route + (editor.id ? "/" + editor.id : ""),
        editor.deleting ? "DELETE" : editor.id ? "PUT" : "POST",
        editor.deleting
          ? undefined
          : editor.kind === "chat"
            ? { title: editor.name, project_id: editor.project_id || null }
            : { name: editor.name },
      );
      let next: string | undefined;
      if (editor.kind === "project" && !editor.id) {
        const chat = await request<Chat>("/conversations", "POST", {
          project_id: result.id,
        });
        next = chat.id;
      }
      setEditor(null);
      await onChanged(next);
    });
  }
  function rows(projectId: string | null) {
    return chats
      .filter(
        (chat) =>
          chat.project_id === projectId &&
          chat.title.toLocaleLowerCase().includes(filter.toLocaleLowerCase()),
      )
      .map((chat) => (
        <div
          className={"chat-list-row " + (chat.id === active ? "active" : "")}
          key={chat.id}
        >
          <button
            className="chat-select"
            title={chat.title}
            disabled={disabled || working}
            aria-current={chat.id === active ? "page" : undefined}
            onClick={() => void run(() => onSelect(chat.id))}
          >
            <span>◈</span>
            <span>{chat.title}</span>
          </button>
          <button
            className="chat-menu"
            aria-label={"Управление чатом «" + chat.title + "»"}
            disabled={disabled || working}
            onClick={() =>
              setEditor({
                kind: "chat",
                id: chat.id,
                name: chat.title,
                project_id: chat.project_id || "",
              })
            }
          >
            ⋯
          </button>
        </div>
      ));
  }
  return (
    <>
      <div className="chat-spaces">
        <div className="chat-space-actions">
          <button
            className="outline"
            disabled={disabled || working}
            onClick={() => void create()}
          >
            ＋ Новый чат
          </button>
          <button
            className="subtle"
            disabled={disabled || working}
            onClick={() =>
              setEditor({ kind: "project", name: "", project_id: "" })
            }
          >
            ＋ Проект
          </button>
        </div>
        <input
          className="chat-filter"
          type="search"
          aria-label="Найти чат"
          placeholder="Найти чат…"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
        <div className="chat-tree">
          <div className="chat-group-title">ОБЩИЕ ЧАТЫ</div>
          {rows(null)}
          {projects.map((project) => (
            <details className="project-group" key={project.id} open>
              <summary>
                <span>▱ {project.name}</span>
              </summary>
              <div className="project-actions">
                <button
                  className="subtle"
                  disabled={disabled || working}
                  aria-label={"Новый чат в проекте «" + project.name + "»"}
                  onClick={() => void create(project.id)}
                >
                  ＋ Чат
                </button>
                <button
                  className="subtle"
                  disabled={disabled || working}
                  aria-label={"Управление проектом «" + project.name + "»"}
                  onClick={() =>
                    setEditor({
                      kind: "project",
                      id: project.id,
                      name: project.name,
                      project_id: project.id,
                    })
                  }
                >
                  ⋯
                </button>
              </div>
              {rows(project.id)}
            </details>
          ))}
        </div>
      </div>
      {editor && (
        <div className="space-dialog-backdrop">
          <section
            ref={dialog}
            className="space-dialog card"
            role="dialog"
            aria-modal="true"
            aria-label={
              editor.deleting
                ? "Подтверждение удаления"
                : editor.kind === "chat"
                  ? "Управление чатом"
                  : editor.id
                    ? "Управление проектом"
                    : "Новый проект"
            }
            onKeyDown={(event) => {
              if (event.key === "Escape" && !working) setEditor(null);
              if (event.key === "Tab") {
                const items = Array.from(
                  event.currentTarget.querySelectorAll<HTMLElement>(
                    "button:not(:disabled),input:not(:disabled),select:not(:disabled)",
                  ),
                );
                const first = items[0],
                  last = items.at(-1);
                if (event.shiftKey && document.activeElement === first) {
                  event.preventDefault();
                  last?.focus();
                } else if (!event.shiftKey && document.activeElement === last) {
                  event.preventDefault();
                  first?.focus();
                }
              }
            }}
          >
            <h2>
              {editor.deleting
                ? "Удалить «" + editor.name + "»?"
                : editor.kind === "chat"
                  ? "Настройки чата"
                  : editor.id
                    ? "Настройки проекта"
                    : "Новый независимый проект"}
            </h2>
            {editor.deleting ? (
              <p>
                {editor.kind === "chat"
                  ? "Переписка, документы и предложения памяти этого чата будут удалены. Подтверждённая память сохранится отдельно."
                  : "Все чаты, документы, память, заметки, задачи, события календаря и сценарии этого проекта будут удалены. Общая память останется."}
              </p>
            ) : (
              <>
                <label>
                  Название {editor.kind === "chat" ? "чата" : "проекта"}
                  <input
                    autoFocus
                    maxLength={100}
                    value={editor.name}
                    onChange={(event) =>
                      setEditor({ ...editor, name: event.target.value })
                    }
                  />
                </label>
                {editor.kind === "chat" ? (
                  <>
                    <label>
                      Расположение чата
                      <select
                        value={editor.project_id}
                        onChange={(event) =>
                          setEditor({
                            ...editor,
                            project_id: event.target.value,
                          })
                        }
                      >
                        <option value="">Общие чаты</option>
                        {projects.map((project) => (
                          <option value={project.id} key={project.id}>
                            {project.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <p className="help">
                      При переносе перемещаются история и файлы. Подтверждённая
                      память остаётся в прежнем пространстве, предложения и
                      контекст уточнений сбрасываются.
                    </p>
                  </>
                ) : (
                  <p className="help">
                    У проекта своя память, заметки, задачи и календарь. Общая
                    память и история других чатов не передаются его модели. Имя
                    ассистента, характер и выбор моделей остаются общими.
                  </p>
                )}
              </>
            )}
            <div className="button-row">
              <button
                className="primary"
                disabled={disabled || working || !editor.name.trim()}
                onClick={() => void save()}
              >
                {editor.deleting
                  ? "Удалить навсегда"
                  : editor.id
                    ? "Сохранить изменения"
                    : "Создать проект"}
              </button>
              <button
                className="subtle"
                disabled={working}
                onClick={() => setEditor(null)}
              >
                Отмена
              </button>
              {editor.id && !editor.deleting && (
                <button
                  className="subtle danger"
                  disabled={disabled || working}
                  onClick={() => setEditor({ ...editor, deleting: true })}
                >
                  {editor.kind === "chat" ? "Удалить чат" : "Удалить проект"}
                </button>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
