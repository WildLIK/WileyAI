import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

const script = await readFile("core/yandex_music_page.js", "utf8");
const action = (page: Page, value: object) => page.evaluate("(" + script + ")(" + JSON.stringify(value) + ")");
const choice = { action: "select_target", query: "Fall Out Boy", search_id: "a".repeat(32), id: "41", title: "7 Minutes In Heaven", artists: "Fall Out Boy" };
const row = (id: string, title: string) => `<div data-test-id="SEARCH_TRACK_CARD"><a data-test-id="TRACK_TITLE" href="/track/${id}">${title}</a><a href="/artist/1">Fall Out Boy</a><button data-test-id="PLAY_BUTTON" data-id="${id}">Play ${id}</button></div>`;

test.beforeEach(async ({ page }) => {
  await page.setContent(`<input data-test-id="SEARCH_PAGE_SEARCH_INPUT" value="Fall Out Boy"><main>${row("41", "7 Minutes In Heaven")}${row("42", "Other song")}</main>`);
  await action(page, { action: "search", query: choice.query, search_id: choice.search_id });
  await expect.poll(async () => (await action(page, { action: "results", query: choice.query, search_id: choice.search_id })).ready).toBe(true);
});

test("365a selection binds ID and metadata after React row reorder", async ({ page }) => {
  await page.locator("main").evaluate((main, html) => { main.innerHTML = html; }, row("42", "Other song") + row("41", "7 Minutes In Heaven"));
  await expect.poll(async () => (await action(page, { action: "results", query: choice.query, search_id: choice.search_id })).ready).toBe(true);
  await page.evaluate(() => { document.querySelector("main")!.onclick = (e) => { (window as any).clicked = (e.target as HTMLElement).dataset.id; }; });
  const target = await action(page, choice);
  expect(target.reveal).toBe(false);
  await page.mouse.click(target.x, target.y);
  expect(await page.evaluate(() => (window as any).clicked)).toBe("41");
});

test("365a missing or changed result fails without hitting a different row", async ({ page }) => {
  await page.locator('[data-test-id="SEARCH_TRACK_CARD"]').first().evaluate((node) => node.remove());
  await expect.poll(async () => (await action(page, { action: "results", query: choice.query, search_id: choice.search_id })).ready).toBe(true);
  await expect(action(page, choice)).rejects.toThrow("search_results_changed");
  await page.locator("main").evaluate((main, html) => { main.innerHTML = html; }, row("41", "Changed song"));
  await expect.poll(async () => (await action(page, { action: "results", query: choice.query, search_id: choice.search_id })).ready).toBe(true);
  await expect(action(page, choice)).rejects.toThrow("search_results_changed");
});

test("365a a missing play button and stale search never yield a target", async ({ page }) => {
  await page.locator('button[data-id="41"]').evaluate((button) => button.remove());
  await expect(action(page, choice)).rejects.toThrow("search_not_ready");
  await expect(action(page, { ...choice, search_id: "b".repeat(32) })).rejects.toThrow("search_id_changed");
});
