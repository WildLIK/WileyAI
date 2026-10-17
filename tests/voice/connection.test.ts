import test from "node:test";
import assert from "node:assert/strict";
import { validateConnection } from "../../src/connection.ts";

test("startup client: missing or malformed IPC connection has a readable error, without echoing credentials", () => {
  const token = "a".repeat(64);
  for (const value of [
    undefined,
    null,
    {},
    { url: "http://127.0.0.1:12" },
    { url: "https://example.com", token },
    { url: "http://127.0.0.1:65536", token },
    { url: "http://127.0.0.1:0", token },
    { url: "http://127.0.0.1:12/path", token },
    { url: "http://127.0.0.1:12", token: "short-secret" },
  ]) {
    assert.throws(
      () => validateConnection(value),
      (error) => {
        assert.match((error as Error).message, /Локальное ядро/);
        assert.doesNotMatch(
          (error as Error).message,
          /short-secret|aaaaaaaa|TypeError|reading/,
        );
        return true;
      },
    );
  }
});

test("startup client: valid local connection is copied and accepted", () => {
  const value = { url: "http://127.0.0.1:51234", token: "f".repeat(64) };
  const result = validateConnection(value);
  assert.deepEqual(result, value);
  assert.notEqual(result, value);
});
