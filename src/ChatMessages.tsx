import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

export interface HistoryFocus {
  id: string;
  version: number;
  terms: string[];
}

export function ChatMessages({
  children,
  chat,
  requestKey,
  target,
  onLatest,
}: {
  children: ReactNode;
  chat: string;
  requestKey: number;
  target?: HistoryFocus | null;
  onLatest?: () => void;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [below, setBelow] = useState(false);
  const update = () => {
    const element = viewport.current;
    if (!element) return;
    const away =
      element.scrollHeight - element.scrollTop - element.clientHeight > 80;
    setBelow(away);
    follow.current = !away;
  };
  const bottom = () => {
    const element = viewport.current;
    if (!element) return;
    follow.current = true;
    element.scrollTop = element.scrollHeight;
    setBelow(false);
  };
  useLayoutEffect(() => {
    if (!target) {
      bottom();
      return;
    }
    const element = viewport.current;
    const article = element?.querySelector<HTMLElement>(
      '[data-message-id="' + CSS.escape(target.id) + '"]',
    );
    if (!element || !article) return;
    const match =
      article.querySelector<HTMLElement>("[data-history-match]") || article;
    follow.current = false;
    article.focus({ preventScroll: true });
    element.scrollTop +=
      match.getBoundingClientRect().top -
      element.getBoundingClientRect().top -
      30;
    setBelow(
      element.scrollHeight - element.scrollTop - element.clientHeight > 80,
    );
  }, [chat, requestKey, target?.version]);
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      if (follow.current) bottom();
      else if (viewport.current)
        setBelow(
          viewport.current.scrollHeight -
            viewport.current.scrollTop -
            viewport.current.clientHeight >
            80,
        );
    });
    if (content.current) observer.observe(content.current);
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  return (
    <div className="message-scroll-area">
      <div
        className="messages"
        aria-live="polite"
        ref={viewport}
        onScroll={update}
      >
        <div ref={content}>{children}</div>
      </div>
      {below && (
        <button
          className="chat-scroll-bottom"
          aria-label="К последнему сообщению"
          title="Прокрутить чат вниз"
          onClick={onLatest || bottom}
        >
          ↓
        </button>
      )}
    </div>
  );
}
