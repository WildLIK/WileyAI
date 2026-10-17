export interface Connection {
  url: string;
  token: string;
}

export function validateConnection(value: unknown): Connection {
  if (
    value &&
    typeof value === "object" &&
    "url" in value &&
    "token" in value &&
    typeof value.url === "string" &&
    typeof value.token === "string"
  ) {
    const match = value.url.match(/^http:\/\/127\.0\.0\.1:([1-9]\d{0,4})$/);
    if (
      match &&
      Number(match[1]) <= 65535 &&
      /^[a-f0-9]{64}$/i.test(value.token)
    )
      return { url: value.url, token: value.token };
  }
  throw new Error(
    "Локальное ядро ещё не предоставило подключение. Повторите подключение или перезапустите WileyAI.",
  );
}
