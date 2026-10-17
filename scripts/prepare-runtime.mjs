// Prepare a relocatable base runtime. Never copy the developer's .venv or data.
import { spawnSync } from "node:child_process";
import { cp, mkdir, rm, writeFile, readFile } from "node:fs/promises";
import { resolve, join, sep } from "node:path";

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
await mkdir(staging, { recursive: true });
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
const requirements = run(
  uv,
  ["export", "--locked", "--no-dev", "--no-emit-project", "--no-hashes"],
  true,
);
await writeFile(join(staging, "base.txt"), requirements + "\n");
run(uv, [
  "pip",
  "install",
  "--break-system-packages",
  "--python",
  join(pythonRoot, "python.exe"),
  "-r",
  join(staging, "base.txt"),
]);
await mkdir(join(staging, "requirements"), { recursive: true });
for (const [id, extra] of [
  ["whisper", "voice"],
  ["piper", "piper"],
  ["silero", "tts"],
]) {
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
for (const name of ["react", "react-dom", "three", "@pixiv/three-vrm"]) {
  const directory = join(root, "node_modules", name);
  const files = await readdir(directory);
  const license = files.find((file) =>
    /^licen[sc]e(?:\.txt|\.md)?$/i.test(file),
  );
  if (!license) throw new Error("Missing dependency license: " + name);
  await cp(
    join(directory, license),
    join(staging, "licenses", name.replaceAll("/", "_") + "-LICENSE.txt"),
  );
}
run(join(pythonRoot, "python.exe"), [
  "-c",
  "import fastapi,uvicorn,keyring,psutil,docx,pypdf; print('Bundled core dependencies OK')",
]);
await writeFile(
  join(staging, "build-info.json"),
  JSON.stringify(
    {
      version: JSON.parse(await readFile(join(root, "package.json"))).version,
      python: "3.12.13",
      platform: "win32-x64",
    },
    null,
    2,
  ),
);
console.log("Standalone runtime ready:", staging);
