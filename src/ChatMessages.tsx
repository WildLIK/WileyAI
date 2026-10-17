import { useEffect, useRef, useState, type ReactNode } from "react";

export function ChatMessages({
  children,
  chat,
  requestKey,
}: {
  children: ReactNode;
  chat: string;
  requestKey: number;
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
  useEffect(() => {
    bottom();
  }, [chat, requestKey]);
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
          onClick={bottom}
        >
          ↓
        </button>
      )}
    </div>
  );
}
