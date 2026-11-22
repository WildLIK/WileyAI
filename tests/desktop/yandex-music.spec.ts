import {
  test,
  expect,
  type Page,
  _electron as electron,
} from "@playwright/test";
import { readFile, mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

test.use({
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
  },
});

const script = await readFile("core/yandex_music_page.js", "utf8");
const action = (page: Page, value: object) =>
  page.evaluate("(" + script + ")(" + JSON.stringify(value) + ")");

test("Wave target is unique, enabled and unobscured; preparing never plays", async ({ page }) => {
  await page.setContent('<button data-test-id="MY_VIBE_PLAY_BUTTON" aria-label="Воспроизведение Моей волны">Wave</button>');
  await page.evaluate(() => { document.querySelector('button')!.onclick = () => { throw new Error('Unexpected playback'); }; });
  const target = await action(page, { action: "wave_target" });
  expect(target.x).toBeGreaterThan(0);
  await page.setContent('<section data-test-id="PLAYERBAR_DESKTOP"><button data-test-id="PAUSE_BUTTON">Pause</button></section><button data-test-id="MY_VIBE_PAUSE_BUTTON" aria-label="Пауза Моей волны">Wave pause</button>');
  expect(await action(page, { action: "wave_target" })).toEqual({ already_playing: true });
  await page.setContent('<button data-test-id="MY_VIBE_PLAY_BUTTON" aria-label="Воспроизведение Моей волны">Wave</button>');
  await page.locator("button").evaluate((e: HTMLButtonElement) => { e.disabled = true; });
  await expect(action(page, { action: "wave_target" })).rejects.toThrow("недоступна");
  await page.locator("button").evaluate((e: HTMLButtonElement) => { e.disabled = false; e.after(e.cloneNode(true)); });
  await expect(action(page, { action: "wave_target" })).rejects.toThrow("единственная");
  await page.locator("button").last().evaluate((e) => e.remove());
  await page.evaluate(() => { const e = document.createElement("div"); e.style.cssText = "position:fixed;inset:0;z-index:100;background:white"; document.body.append(e); });
  await expect(action(page, { action: "wave_target" })).rejects.toThrow("перекрыта");
});

test("Wave waits for initial React mount and reports a missing button without playback", async ({ page }) => {
  await page.setContent("<main></main>");
  await page.evaluate(() => { setTimeout(() => { document.querySelector("main")!.innerHTML = '<button disabled data-test-id="MY_VIBE_PLAY_BUTTON" aria-label="Воспроизведение Моей волны">Wave</button>'; setTimeout(() => { document.querySelector<HTMLButtonElement>("button")!.disabled = false; }, 500); }, 1200); });
  expect((await action(page, { action: "wave_target" })).x).toBeGreaterThan(0);
  await expect(page.locator("button")).toBeEnabled();
  await page.setContent('<a data-test-id="NAVBAR_NAVIGATION_ITEM_HOME" href="/">Home</a>');
  await page.locator("a").evaluate((a: HTMLAnchorElement) => { a.onclick = (e) => e.preventDefault(); });
  await expect(action(page, { action: "wave_target" })).rejects.toThrow("WILEY_MUSIC/button_missing/");
});

test("Song selection rejects replaced, expired or edited searches even with identical rows", async ({ page }) => {
  await page.setContent('<input data-test-id="SEARCH_PAGE_SEARCH_INPUT"><div data-test-id="SEARCH_TRACK_CARD"><a data-test-id="TRACK_TITLE" href="/track/42">Numb</a><button data-test-id="PLAY_BUTTON">Play</button></div>');
  const query = "Numb", search_id = "a".repeat(32);
  await action(page, { action: "search", query, search_id });
  // Identical results are valid for a repeated query, once stable.
  await page.evaluate(() => { const w = window as unknown as { __wileyMusicSearch: { previous: string; started: number; changed: number; last: string } }; w.__wileyMusicSearch.previous = "Numb"; w.__wileyMusicSearch.started -= 2000; });
  await expect.poll(async () => (await action(page, { action: "results", query, search_id })).ready).toBe(true);
  const selection = { action: "select_target", query, search_id, id: "42", title: "Numb", artists: "" };
  expect((await action(page, selection)).reveal).toBe(false);
  await expect(action(page, { ...selection, search_id: "b".repeat(32) })).rejects.toThrow("устарел");
  await page.evaluate(() => { const w = window as unknown as { __wileyMusicSearch: { started: number } }; w.__wileyMusicSearch.started -= 301000; });
  await expect(action(page, selection)).rejects.toThrow("устарел");
  await page.locator("input").fill("Changed query");
  await expect(action(page, selection)).rejects.toThrow("изменился");
});

test("Repeated music searches keep the mounted field without navigating again", async ({ page }) => {
  await page.setContent('<a href="/search">Search</a><input data-test-id="SEARCH_PAGE_SEARCH_INPUT">');
  await page.evaluate(() => {
    (window as unknown as { navigations: number }).navigations = 0;
    document.querySelector('a')!.onclick = (event) => {
      event.preventDefault();
      (window as unknown as { navigations: number }).navigations++;
    };
  });
  await action(page, { action: "search", query: "Numb", search_id: "a".repeat(32) });
  await action(page, { action: "search", query: "Other", search_id: "b".repeat(32) });
  expect(await page.locator('input').inputValue()).toBe("Other");
  expect(await page.evaluate(() => (window as unknown as { navigations: number }).navigations)).toBe(0);
  await expect(action(page, { action: "results", query: "Other", search_id: "a".repeat(32) })).rejects.toThrow("search_id_changed");
});

test("Search waits for replacement of the React input before recording the query", async ({ page }) => {
  await page.setContent('<a href="/search">Search</a><main></main>');
  await page.evaluate(() => {
    document.querySelector('a')!.onclick = (event) => {
      event.preventDefault();
      setTimeout(() => { document.querySelector('main')!.innerHTML = '<input data-test-id="SEARCH_PAGE_SEARCH_INPUT" data-stage="old">'; }, 20);
      setTimeout(() => { document.querySelector('main')!.innerHTML = '<input data-test-id="SEARCH_PAGE_SEARCH_INPUT" data-stage="new">'; }, 150);
    };
  });
  await action(page, { action: "search", query: "Numb", search_id: "a".repeat(32) });
  expect(await page.locator('input[data-stage="new"]').inputValue()).toBe("Numb");
  expect(await page.evaluate(() => (window as unknown as { __wileyMusicSearch: { query: string } }).__wileyMusicSearch.query)).toBe("Numb");
});

test("Search diagnostics distinguish edited fields, missing sessions and TTL", async ({ page }) => {
  await page.setContent('<input data-test-id="SEARCH_PAGE_SEARCH_INPUT">');
  const request = { action: "results", query: "Numb", search_id: "a".repeat(32) };
  await action(page, { ...request, action: "search" });
  await page.locator('input').fill('Changed');
  await expect(action(page, request)).rejects.toThrow("search_input_changed");
  await page.locator('input').fill('Numb');
  await page.evaluate(() => { (window as unknown as { __wileyMusicSearch: { started: number } }).__wileyMusicSearch.started -= 301000; });
  await expect(action(page, request)).rejects.toThrow("search_expired");
  await page.evaluate(() => { delete (window as unknown as { __wileyMusicSearch?: object }).__wileyMusicSearch; });
  await expect(action(page, request)).rejects.toThrow("search_session_missing");
});

test("Yandex renderer: scoped controls, idempotent favorites, new search results and volume", async ({
  page,
}) => {
  await page.setContent(`<section data-test-id="PLAYERBAR_DESKTOP">
    <a href="/track/1" data-test-id="TRACK_TITLE">Old song</a><a href="/artist/1">Other Artist</a>
    <button data-test-id="PLAY_BUTTON">Play</button><button data-test-id="NEXT_TRACK_BUTTON">Next</button>
    <button data-test-id="PREVIOUS_TRACK_BUTTON">Previous</button><button data-test-id="LIKE_BUTTON" aria-pressed="false">Like</button>
    <span data-test-id="CHANGE_VOLUME_SLIDER" style="display:block;width:200px;height:20px"><span role="slider" aria-valuenow="0.4" aria-valuemin="0" aria-valuemax="1" style="display:block;width:5px;height:20px"></span></span>
    </section><a href="/search">Search</a><input data-test-id="SEARCH_PAGE_SEARCH_INPUT" />
    <div id="results"><div data-test-id="SEARCH_TRACK_CARD"><a href="/track/1" data-test-id="TRACK_TITLE">Old song</a><a href="/artist/1">Other Artist</a><button data-test-id="PLAY_BUTTON">Play old</button></div></div>`);
  await page.evaluate(() => {
    Object.assign(window, { played: [] });
    const root = document.querySelector("section")!;
    root.addEventListener("click", (event) => {
      const button = (event.target as HTMLElement).closest("button")!;
      const key = button?.dataset.testId;
      if (key === "PLAY_BUTTON") {
        button.dataset.testId = "PAUSE_BUTTON";
        button.textContent = "Pause";
      } else if (key === "PAUSE_BUTTON") {
        button.dataset.testId = "PLAY_BUTTON";
        button.textContent = "Play";
      } else if (key === "LIKE_BUTTON")
        button.setAttribute(
          "aria-pressed",
          String(button.getAttribute("aria-pressed") !== "true"),
        );
      else if (key?.includes("TRACK_BUTTON"))
        root
          .querySelector("a")!
          .setAttribute(
            "href",
            "/track/" + (key.startsWith("NEXT") ? "2" : "1"),
          );
    });
    document.querySelector<HTMLAnchorElement>('a[href="/search"]')!.onclick = (
      event,
    ) => event.preventDefault();
    document.querySelector("input")!.addEventListener("input", () =>
      setTimeout(() => {
        document.querySelector("#results")!.innerHTML =
          '<div data-test-id="SEARCH_TRACK_CARD"><a href="/track/42" data-test-id="TRACK_TITLE">With You</a><a href="/artist/2">Linkin Park</a><button data-test-id="PLAY_BUTTON">Play found</button></div>';
      }, 1300),
    );
    document.querySelector("#results")!.addEventListener("click", (event) => {
      if (event.isTrusted)
        (window as unknown as { played: string[] }).played.push("42");
    });
  });
  expect((await action(page, { action: "status" })).volume).toBe(40);
  await action(page, { action: "play" });
  await action(page, { action: "play" });
  expect((await action(page, { action: "status" })).playing).toBe(true);
  await action(page, { action: "pause" });
  expect((await action(page, { action: "status" })).playing).toBe(false);
  await action(page, { action: "like" });
  await action(page, { action: "like" });
  expect((await action(page, { action: "status" })).liked).toBe(true);
  await action(page, { action: "unlike" });
  expect((await action(page, { action: "status" })).liked).toBe(false);
  await page
    .locator('[data-test-id="LIKE_BUTTON"]')
    .evaluate((node) => node.removeAttribute("aria-pressed"));
  await expect(action(page, { action: "like" })).rejects.toThrow("не изменено");
  const target = await action(page, { action: "volume_target", value: 80 });
  const box = (await page
    .locator('[data-test-id="CHANGE_VOLUME_SLIDER"]')
    .boundingBox())!;
  expect(target.x).toBeCloseTo(box.x + box.width * 0.8);
  const query = 'Linkin Park With You "); alert(1); //';
  await action(page, { action: "search", query });
  expect((await action(page, { action: "results", query })).ready).toBe(false);
  await expect(
    action(page, {
      action: "select",
      query,
      id: "1",
      title: "Old song",
      artists: "Other Artist",
    }),
  ).rejects.toThrow("не подтверждены");
  await expect
    .poll(async () => (await action(page, { action: "results", query })).ready)
    .toBe(true);
  const results = await action(page, { action: "results", query });
  expect(results.rows).toEqual([
    { id: "42", title: "With You", artists: "Linkin Park" },
  ]);
  await expect(
    action(page, {
      action: "select",
      query,
      id: "42",
      title: "Changed title",
      artists: "Linkin Park",
    }),
  ).rejects.toThrow("изменились");
  await action(page, { action: "select", query, ...results.rows[0] });
  expect(
    await page.evaluate(
      () => (window as unknown as { played: string[] }).played,
    ),
  ).toEqual([]); // Synthetic element.click() is not proof of native playback.
  const songTarget = await action(page, {
    action: "select_target",
    query,
    ...results.rows[0],
  });
  expect(songTarget.reveal).toBe(false);
  await page.mouse.click(songTarget.x, songTarget.y);
  expect(
    await page.evaluate(
      () => (window as unknown as { played: string[] }).played,
    ),
  ).toEqual(["42"]);
});

test("Yandex connection UI preserves restart offer and requires the dedicated button", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-yandex-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  const connections: unknown[] = [];
  try {
    const page = await app.firstWindow();
    await page.route("**/music/yandex**", async (route) => {
      const url = route.request().url();
      if (url.endsWith("/connect")) {
        const body = route.request().postDataJSON();
        connections.push(body);
        return route.fulfill({
          json: body.restart
            ? {
                connected: true,
                selected: true,
                text: "Тестовый плеер подключён",
              }
            : {
                connected: false,
                restart_required: true,
                text: "Нужен перезапуск",
              },
        });
      }
      return route.fulfill({
        json: {
          connected: connections.length > 1,
          selected: connections.length > 1,
          enabled: true,
        },
      });
    });
    await page.getByRole("button", { name: "⌘ Команды", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "Яндекс Музыка",
      exact: true,
    });
    await panel
      .getByRole("button", { name: "Подключить Яндекс Музыку", exact: true })
      .click();
    await expect(
      panel.getByText("Текущее воспроизведение остановится.", { exact: false }),
    ).toBeVisible();
    expect(connections).toEqual([{}]);
    await panel
      .getByRole("button", { name: "Перезапустить и подключить", exact: true })
      .click();
    await expect(
      panel.getByRole("button", { name: "Плей", exact: true }),
    ).toBeEnabled();
    expect(connections).toEqual([{}, { restart: true }]);
  } finally {
    await app.close();
  }
});

test("Yandex desktop metadata works without numeric href or enabled Discord helper", async ({
  page,
}) => {
  await page.setContent(`<section data-test-id="PLAYERBAR_DESKTOP">
    <a data-test-id="TRACK_TITLE" href="/album/track">With You</a><a data-test-id="SEPARATED_ARTIST_TITLE" href="/artist">Linkin Park</a>
    <button data-test-id="PAUSE_BUTTON">Pause</button><button data-test-id="LIKE_BUTTON" aria-pressed="false">Like</button>
    <input data-test-id="TIMECODE_SLIDER" type="range" max="200" value="30">
    <div style="opacity:0"><input data-test-id="CHANGE_VOLUME_SLIDER" type="range" min="0" max="1" step=".01" value=".7"></div>
    <button data-test-id="CHANGE_VOLUME_BUTTON">Volume</button>
    </section><div data-test-id="SEARCH_TRACK_CARD"><a data-test-id="TRACK_TITLE" href="/album/track">Numb</a><button data-test-id="PLAY_BUTTON">Play</button></div>`);
  await page.evaluate(() => {
    Object.assign(window, {
      __getPlayerState: () => ({ enabled: false, data: null }),
    });
    for (const [selector, id, title] of [
      ['section [data-test-id="TRACK_TITLE"]', "42", "With You"],
      ['[data-test-id="SEARCH_TRACK_CARD"] a', "43", "Numb"],
    ]) {
      const node = document.querySelector(selector)!;
      let fiber: { memoizedProps: object; return: unknown } = {
        memoizedProps: {
          track: { id, title, artists: [{ name: "Linkin Park" }] },
        },
        return: null,
      };
      for (let depth = 0; depth < 15; depth++)
        fiber = { memoizedProps: {}, return: fiber };
      Object.assign(node, { __reactFiber$fixture: fiber });
    }
  });
  const state = await action(page, { action: "status" });
  expect(state).toMatchObject({
    available: true,
    id: "42",
    title: "With You",
    artists: "Linkin Park",
    playing: true,
    position: 30,
    volume: 70,
  });
  expect(await action(page, { action: "results" })).toEqual([
    { id: "43", title: "Numb", artists: "Linkin Park" },
  ]);
  const reveal = await action(page, { action: "volume_target", value: 40 });
  expect(reveal.reveal).toBe(true);
});

test("Yandex connection errors stay readable and the selected source remains visible", async () => {
  const data = await mkdtemp(join(tmpdir(), "wiley-yandex-error-"));
  const app = await electron.launch({
    args: ["--mute-audio", "."],
    env: { ...process.env, WILEYAI_TEST: "1", WILEYAI_DATA_DIR: data },
  });
  try {
    const page = await app.firstWindow();
    await page.route("**/music/yandex**", async (route) => {
      if (route.request().url().endsWith("/connect"))
        return route.fulfill({
          status: 400,
          json: {
            detail:
              "Запуск отменён в подтверждении Windows. Повторите подключение.",
          },
        });
      return route.fulfill({
        json: { connected: false, selected: true, enabled: true },
      });
    });
    await page.getByRole("button", { name: "⌘ Команды", exact: true }).click();
    const panel = page.getByRole("region", {
      name: "Яндекс Музыка",
      exact: true,
    });
    await panel
      .getByRole("button", { name: "Подключить Яндекс Музыку", exact: true })
      .click();
    await expect(panel.getByRole("alert")).toHaveText(
      "Запуск отменён в подтверждении Windows. Повторите подключение.",
    );
    await expect(
      panel.getByText("Выбрана Яндекс Музыка, но связь недоступна.", {
        exact: false,
      }),
    ).toBeVisible();
    await expect(
      panel.getByRole("button", {
        name: "Подключить Яндекс Музыку",
        exact: true,
      }),
    ).toBeEnabled();
  } finally {
    await app.close();
  }
});
