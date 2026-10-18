// Bounded renderer adapter. No account tokens, cookies, history or filesystem APIs.
async function wileyMusic(command) {
  const id = (name) => `[data-test-id="${name}"]`;
  const bar = () => document.querySelector(id("PLAYERBAR_DESKTOP"));
  const visible = (node) => node && node.getBoundingClientRect().width > 0 && node.getBoundingClientRect().height > 0;
  const find = (root, selector) => [...(root?.querySelectorAll(selector) || [])].find(visible);
  const text = (node) => (node?.textContent || "").trim().slice(0, 200);
  const searchInput = () => find(document, id("SEARCH_PAGE_SEARCH_INPUT") + ',input[class*="SearchPage_input"],input[type="search"]');
  const sliderNode = (visibleOnly = false) => {
    const wrapper = bar()?.querySelector(id("CHANGE_VOLUME_SLIDER"));
    if (visibleOnly && wrapper?.checkVisibility && !wrapper.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return null;
    return wrapper?.matches('input[type="range"],[role="slider"]') ? wrapper : wrapper?.querySelector('input[type="range"],[role="slider"]');
  };
  const volume = () => {
    const slider = sliderNode();
    if (!slider) return null;
    const range = slider instanceof HTMLInputElement;
    const raw = range ? slider.value : slider.getAttribute("aria-valuenow");
    const min = Number(range ? slider.min : slider.getAttribute("aria-valuemin")) || 0;
    const max = Number(range ? slider.max : slider.getAttribute("aria-valuemax")) || 1;
    return raw !== null && raw !== "" && max > min ? Math.round((Number(raw) - min) / (max - min) * 100) : null;
  };
  const meta = (root) => {
    const link = root?.querySelector(id("TRACK_TITLE")) || root?.querySelector('a[href*="/track/"]');
    // Desktop routes omit entity IDs from href. Read only the track prop of
    // the nearest title component, like the mod's own bounded metadata reader.
    let model = null, fiber = link?.[Object.keys(link || {}).find((key) => key.startsWith("__reactFiber$"))];
    for (let n = 0; fiber && n < 32; n++, fiber = fiber.return) {
      const candidate = fiber.memoizedProps?.track;
      if (candidate && typeof candidate.title === "string" && /^\d+$/.test(String(candidate.id || ""))) { model = candidate; break; }
    }
    const title = text(link) || model?.title || "", version = text(root?.querySelector(id("TRACK_VERSION"))) || model?.version || "";
    const artists = model?.artists?.map((a) => a.name).filter((name) => typeof name === "string").join(", ");
    return { id: model ? String(model.id) : link?.getAttribute("href")?.match(/\/track\/(\d+)/)?.[1] || "", title: (title + (version && !title.includes(version) ? " (" + version + ")" : "")).slice(0, 300),
      artists: artists || [...(root?.querySelectorAll(id("SEPARATED_ARTIST_TITLE") + "," + id("ARTIST_TITLE") + ',a[href*="/artist/"]') || [])].map(text).join(", ").slice(0, 300) };
  };
  const state = () => {
    let details = null;
    try { details = window.__getPlayerState?.()?.data; } catch { /* Optional mod helper. */ }
    const root = bar(), track = meta(root);
    const like = find(root, id("LIKE_BUTTON"));
    const pressed = like?.getAttribute("aria-pressed");
    return { available: !!root && !!(details?.trackMeta?.id || track.id), id: String(details?.trackMeta?.id || track.id), title: String(details?.trackMeta?.title || track.title).slice(0, 200),
      artists: details?.trackMeta?.artists?.map((a) => a.name).join(", ").slice(0, 300) || track.artists,
      playing: typeof details?.isPlaying === "boolean" ? details.isPlaying : !!find(root, id("PAUSE_BUTTON")), position: Number(details?.playback?.position ?? root?.querySelector(id("TIMECODE_SLIDER"))?.value) || 0,
      liked: pressed === "true" ? true : pressed === "false" ? false : null,
      volume: volume() };
  };
  const click = (root, selector) => {
    const button = find(root, selector);
    if (!button || button.disabled || button.getAttribute("aria-disabled") === "true") throw new Error("Элемент управления недоступен в этой версии Яндекс Музыки");
    button.click();
  };
  if (command.action === "status") return state();
  if (command.action === "search") {
    const link = find(document, 'a[href="/search"],a[href^="/search?"]');
    if (link) link.click();
    for (let n = 0; n < 40; n++) {
      const input = searchInput();
      if (input) {
        window.__wileyMusicSearch = { query: command.query, previous: input.value, signature: JSON.stringify(await wileyMusic({action: "results"})), started: performance.now(), changed: 0, last: "" };
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, command.query);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return { searching: true };
      }
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error("Не найдено поле поиска Яндекс Музыки");
  }
  if (["results", "select", "select_target"].includes(command.action)) {
    const nodes = [...document.querySelectorAll(id("SEARCH_TRACK_CARD") + ',[class*="SearchBestResultsTrackBlock_root"] [class*="CommonTrack_root"],[class*="SearchTrackList_root"] [class*="CommonTrack_root"]')].filter(visible);
    const rows = nodes.map((node) => ({ node, ...meta(node) })).filter((row) => row.id && row.title).filter((row, i, list) => list.findIndex((other) => other.id === row.id) === i).slice(0, 20);
    const plain = rows.map(({ node, ...row }) => row);
    if (!command.query && command.action === "results") return plain;
    const pending = window.__wileyMusicSearch;
    const signature = JSON.stringify(plain);
    if (!pending || pending.query !== command.query || searchInput()?.value !== command.query) throw new Error("Поисковый запрос изменился. Повторите поиск песни");
    if (pending.last !== signature) { pending.last = signature; pending.changed = performance.now(); }
    const ready = performance.now() - pending.started >= 800 && performance.now() - pending.changed >= 450 && (pending.previous === pending.query || pending.signature !== signature);
    if (command.action === "results") return { rows: plain, ready };
    if (!ready) throw new Error("Новые результаты поиска ещё не подтверждены");
    const row = rows.find((row) => row.id === command.id);
    if (!row || row.title !== command.title || row.artists !== command.artists) throw new Error("Результаты поиска изменились. Повторите поиск песни");
    if (command.action === "select_target") {
      const button = find(row.node, id("PLAY_BUTTON") + "," + id("PLAY_BUTTON_WITH_COVER"));
      if (!button || button.disabled || button.getAttribute("aria-disabled") === "true") throw new Error("Кнопка воспроизведения найденной песни недоступна");
      button.scrollIntoView({ block: "center", inline: "nearest", behavior: "instant" });
      const box = button.getBoundingClientRect(), x = box.left + box.width / 2, y = box.top + box.height / 2;
      if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) throw new Error("Кнопка найденной песни находится за пределами окна");
      return { x, y, reveal: !button.contains(document.elementFromPoint(x, y)) };
    }
    click(row.node, id("PLAY_BUTTON") + "," + id("PLAY_BUTTON_WITH_COVER"));
    return { dispatched: true };
  }
  const root = bar();
  if (!root) throw new Error("Откройте плеер Яндекс Музыки и выберите трек");
  const before = state();
  if (command.action === "play" && !before.playing) click(root, id("PLAY_BUTTON"));
  else if (command.action === "pause" && before.playing) click(root, id("PAUSE_BUTTON"));
  else if (command.action === "play_pause") click(root, id(before.playing ? "PAUSE_BUTTON" : "PLAY_BUTTON"));
  else if (command.action === "next" || command.action === "previous") click(root, id(command.action === "next" ? "NEXT_TRACK_BUTTON" : "PREVIOUS_TRACK_BUTTON"));
  else if (["like", "unlike", "toggle_like"].includes(command.action)) {
    if (before.liked === null) throw new Error("Не удалось прочитать состояние кнопки «Мне нравится». Избранное не изменено");
    const wanted = command.action === "toggle_like" ? !before.liked : command.action === "like";
    if (before.liked !== wanted) click(root, id("LIKE_BUTTON"));
    return { dispatched: true, wanted };
  } else if (command.action === "volume_target") {
    const slider = sliderNode(true);
    if (!slider) {
      const button = find(root, id("CHANGE_VOLUME_BUTTON"));
      if (!button) throw new Error("Не найден регулятор громкости Яндекс Музыки");
      const box = button.getBoundingClientRect();
      // This button toggles mute on click. Reveal the popup by hover only.
      return { reveal: true, x: box.left + box.width / 2, y: box.top + box.height / 2 };
    }
    const track = find(root, id("CHANGE_VOLUME_SLIDER"));
    const box = track.getBoundingClientRect();
    const vertical = slider.getAttribute("aria-orientation") === "vertical" || box.height > box.width * 2;
    return { x: vertical ? box.left + box.width / 2 : box.left + Math.max(.1, Math.min(box.width - .1, box.width * command.value / 100)), y: vertical ? box.bottom - Math.max(.1, Math.min(box.height - .1, box.height * command.value / 100)) : box.top + box.height / 2 };
  }
  return { dispatched: true };
}
