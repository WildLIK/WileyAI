// Prepare a relocatable base runtime. Never copy the developer's .venv or data.
import { spawnSync } from "node:child_process";
import { cp, mkdir, rm, writeFile, readFile } from "node:fs/promises";
import { resolve, join, sep } from "node:path";
import { createPublicKey, randomUUID } from "node:crypto";

const root = resolve(import.meta.dirname, "..");
const staging = join(root, "local", "packaging");
const run = (exe, args, capture = false) => {
  const result = spawnSync(exe, args, {
    cwd: root,
    encoding: "utf8",
    windowsHide: true,
    stdio: capture ? "pipe" : "inherit",
  });
  if (result.error || result.status !== 0)
    throw new Error(
      result.error?.message || result.stderr || "Runtime preparation failed",
    );
  return result.stdout?.trim();
};
if (process.platform !== "win32" || process.arch !== "x64")
  throw new Error("Build on Windows x64");
const version = JSON.parse(await readFile(join(root, "release-version.json"), "utf8")).version;
if (JSON.parse(await readFile(join(root, "package.json"), "utf8")).version !== version)
  throw new Error("package.json must match release-version.json");
const gitCommit = run("git", ["rev-parse", "HEAD"], true);
const gitDirty = Boolean(run("git", ["status", "--porcelain"], true));
await mkdir(staging, { recursive: true });
const updateKey = process.env.WILEYAI_UPDATE_PUBLIC_KEY || "";
if (updateKey) {
  const parsed = createPublicKey({ key: Buffer.from(updateKey, "base64"), format: "der", type: "spki" });
  if (parsed.asymmetricKeyType !== "ec" || parsed.asymmetricKeyDetails.namedCurve !== "prime256v1")
    throw new Error("WILEYAI_UPDATE_PUBLIC_KEY must be a P-256 public key in DER SPKI/base64 format");
}
await writeFile(join(staging, "update-key.spki"), updateKey + "\n", "ascii");
const pythonRoot = join(staging, "python");
if (
  !resolve(pythonRoot).startsWith(resolve(root) + sep) ||
  resolve(pythonRoot) !== join(root, "local", "packaging", "python")
)
  throw new Error(
    "Refusing to replace a runtime outside the packaging directory",
  );
const uv = process.env.WILEYAI_UV || "uv";
// uv installs python-build-standalone, independent of system Python and PATH.
run(uv, [
  "python",
  "install",
  "3.12.13",
  "--no-bin",
  "--no-registry",
  "--install-dir",
  join(staging, "managed"),
]);
// Prefer the newly prepared managed installation, even if uv also has a global one.
const { readdir } = await import("node:fs/promises");
const installed = (await readdir(join(staging, "managed"))).find((name) =>
  name.startsWith("cpython-3.12.13-windows-x86_64"),
);
if (!installed) throw new Error("Portable Python not found");
await rm(pythonRoot, { recursive: true, force: true }); // fixed, workspace-owned staging path
await cp(join(staging, "managed", installed), pythonRoot, { recursive: true });
// The bundled base runtime installs only the exact locked artifacts.
const requirements = run(
  uv,
  ["export", "--locked", "--no-dev", "--no-emit-project"],
  true,
);
await writeFile(join(staging, "base.txt"), requirements + "\n");
run(uv, [
  "pip",
  "install",
  "--require-hashes",
  "--break-system-packages",
  "--python",
  join(pythonRoot, "python.exe"),
  "-r",
  join(staging, "base.txt"),
]);
await mkdir(join(staging, "requirements"), { recursive: true });
for (const [id, extra] of [
  ["whisper", "voice"],
  ["gigaam", "gigaam"],
  ["endpoint", "endpoint"],
  ["piper", "piper"],
  ["silero", "tts"],
]) {
  // Unhashed on purpose: core/components.py installs these at runtime with
  // --torch-backend cpu, which may select a different torch wheel than the lock.
  const text = run(
    uv,
    [
      "export",
      "--locked",
      "--no-dev",
      "--no-emit-project",
      "--no-hashes",
      "--extra",
      extra,
    ],
    true,
  );
  await writeFile(join(staging, "requirements", id + ".txt"), text + "\n");
}
const uvPath = run("where.exe", [uv], true).split(/\r?\n/)[0];
await mkdir(join(staging, "tools"), { recursive: true });
await cp(uvPath, join(staging, "tools", "uv.exe"));
const uvVersion = run(uv, ["--version"], true).match(
  /^uv ([0-9]+\.[0-9]+\.[0-9]+)/,
)?.[1];
if (!uvVersion) throw new Error("Cannot determine uv version");
for (const license of ["LICENSE-MIT", "LICENSE-APACHE"]) {
  const response = await fetch(
    `https://raw.githubusercontent.com/astral-sh/uv/${uvVersion}/${license}`,
    { signal: AbortSignal.timeout(30000) },
  );
  if (!response.ok)
    throw new Error("Cannot bundle uv license: " + response.status);
  await writeFile(
    join(staging, "tools", "uv-" + license + ".txt"),
    await response.text(),
  );
}
await mkdir(join(staging, "licenses"), { recursive: true });
for (const name of ["react", "react-dom", "three", "@pixiv/three-vrm", "onnxruntime-web", "onnxruntime-common"]) {
  const directory = join(root, "node_modules", name);
  const files = await readdir(directory);
  const license = files.find((file) =>
    /^licen[sc]e(?:\.txt|\.md)?$/i.test(file),
  );
  if (!license && !name.startsWith("onnxruntime-")) throw new Error("Missing dependency license: " + name);
  await cp(
    license ? join(directory, license) : join(root, "assets/voice/ONNX-Runtime-LICENSE.txt"),
    join(staging, "licenses", name.replaceAll("/", "_") + "-LICENSE.txt"),
  );
}
run(join(pythonRoot, "python.exe"), [
  "-c",
  "import fastapi,uvicorn,keyring,psutil,docx,pypdf,telethon,websockets,jwt,cryptography; from zoneinfo import ZoneInfo; ZoneInfo('Asia/Yekaterinburg'); print('Bundled core dependencies, ChatGPT authentication and timezone data OK')",
]);
await writeFile(
  join(staging, "build-info.json"),
  JSON.stringify(
    {
      version,
      build_id: "windows-x64-" + randomUUID(),
      git_commit: gitCommit,
      git_dirty: gitDirty,
      python: "3.12.13",
      platform: "win32-x64",
    },
    null,
    2,
  ),
);
console.log("Standalone runtime ready:", staging);
