package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.widget.*;
import java.util.*;
import java.util.function.BooleanSupplier;

final class AppCatalogPanel {
    private final Activity activity;
    private final MobileUi ui;
    private final AppCatalog catalog;
    private final BooleanSupplier foreground;
    private TextView status;
    private Button refresh;
    private Runnable updateList;
    AppCatalogPanel(Activity activity, MobileUi ui, AppCatalog catalog, BooleanSupplier foreground) { this.activity = activity; this.ui = ui; this.catalog = catalog; this.foreground = foreground; }
    void render(LinearLayout cards) {
        TextView heading = ui.text("Приложения", 20, ui.theme.accentText); heading.setPadding(0, ui.dp(20), 0, ui.dp(8)); cards.addView(heading);
        status = ui.text(catalog.status(), 14, ui.theme.accentText); cards.addView(status);
        for (String role : new String[]{"messenger", "music", "video"}) {
            String prefix = role.equals("music") ? "Музыка: " : role.equals("video") ? "YouTube: " : "Телеграм / мессенджер: ";
            Button preferred = ui.button(prefix + catalog.preferredLabel(role), () -> {});
            preferred.setOnClickListener(v -> chooseRole(role, () -> preferred.setText(prefix + catalog.preferredLabel(role)))); cards.addView(preferred);
        }
        cards.addView(ui.button("Приложения и названия для голоса", () -> show("")));
        refresh = ui.button("Обновить список приложений", catalog::refresh); cards.addView(refresh); refresh();
        LinearLayout info = ui.disclosure(cards, "Как находятся приложения");
        info.addView(ui.text("Читаются системные названия и адреса запуска в текущем профиле Android. Список и ваши псевдонимы остаются на телефоне. При совпадении названий WileyAI уточнит выбор.", 14, ui.theme.secondary));
    }
    void refresh() { if (status != null) status.setText(catalog.status()); if (refresh != null) refresh.setEnabled(!catalog.scanning()); if (updateList != null) updateList.run(); }
    void chooseRole(String role, Runnable changed) {
        LinearLayout form = ui.vertical(); ui.padded(form, 8); EditText search = ui.field("Найти приложение"); search.setSingleLine(true); form.addView(search);
        List<AppRegistry.App> available = new ArrayList<>(catalog.entries());
        if(role.equals("video")) available.removeIf(app -> !app.packageName().equals("com.google.android.youtube") && !app.packageName().equals("app.revanced.android.youtube"));
        List<AppRegistry.App> visible = new ArrayList<>(available);
        ArrayAdapter<AppRegistry.App> adapter = new ArrayAdapter<AppRegistry.App>(activity, android.R.layout.simple_list_item_1, visible) {
            public android.view.View getView(int position, android.view.View recycled, android.view.ViewGroup parent) {
                TextView row = ui.text(getItem(position).label()+(role.equals("video")?getItem(position).packageName().equals("com.google.android.youtube")?" · обычный":" · ReVanced":""), 16, ui.theme.text); row.setPadding(ui.dp(16), ui.dp(14), ui.dp(16), ui.dp(14)); return row;
            }
        };
        ListView list = new ListView(activity); list.setAdapter(adapter); form.addView(list, new LinearLayout.LayoutParams(-1, ui.dp(300)));
        search.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int a, int c, int n) {}
            public void onTextChanged(CharSequence s, int a, int b, int c) { visible.clear(); visible.addAll(AppRegistry.search(available, s.toString())); adapter.notifyDataSetChanged(); }
            public void afterTextChanged(Editable s) {}
        });
        AlertDialog dialog = ui.dialog().setTitle(role.equals("music") ? "Чем открывать музыку?" : role.equals("video") ? "Какой YouTube использовать?" : "Какой мессенджер открывать?").setView(form)
            .setNeutralButton("Сбросить выбор", (d,w) -> { catalog.preferred(role, null); changed.run(); }).setNegativeButton("Отмена", null).show();
        list.setOnItemClickListener((parent, view, position, id) -> { catalog.preferred(role, visible.get(position)); changed.run(); dialog.dismiss(); });
    }
    private void show(String query) {
        LinearLayout form = ui.vertical(); ui.padded(form, 8);
        EditText search = ui.field("Найти по имени, вашему названию или пакету"); search.setSingleLine(true); search.setText(query); form.addView(search);
        List<AppRegistry.App> visible = new ArrayList<>(AppRegistry.search(catalog.entries(), query));
        ArrayAdapter<AppRegistry.App> adapter = new ArrayAdapter<AppRegistry.App>(activity, android.R.layout.simple_list_item_1, visible) {
            @Override public android.view.View getView(int position, android.view.View recycled, android.view.ViewGroup parent) {
                TextView row = recycled instanceof TextView ? (TextView)recycled : ui.text("", 16, ui.theme.text);
                AppRegistry.App app = getItem(position);
                row.setText(app.label() + "\n" + app.packageName() + (app.aliases().isEmpty() ? "" : "\nДля голоса: " + String.join(", ", app.aliases())));
                row.setTag(app);
                row.setSingleLine(false); row.setPadding(ui.dp(12), ui.dp(14), ui.dp(12), ui.dp(14)); row.setMinHeight(ui.dp(64)); return row;
            }
        };
        ListView list = new ListView(new android.view.ContextThemeWrapper(activity, ui.theme.dialogStyle)); list.setAdapter(adapter);
        list.setDivider(new android.graphics.drawable.ColorDrawable(ui.theme.border)); list.setDividerHeight(ui.dp(1));
        form.addView(list, new LinearLayout.LayoutParams(-1, Math.min(ui.dp(340), activity.getResources().getDisplayMetrics().heightPixels * 2 / 5)));
        TextView count = ui.text("Найдено: " + visible.size(), 13, ui.theme.muted); form.addView(count);
        Runnable update = () -> { visible.clear(); visible.addAll(AppRegistry.search(catalog.entries(), search.getText().toString())); adapter.notifyDataSetChanged(); count.setText("Найдено: " + visible.size()); };
        updateList = update;
        search.addTextChangedListener(new TextWatcher() {
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            public void onTextChanged(CharSequence s, int start, int before, int countChanged) {
                update.run();
            }
            public void afterTextChanged(Editable s) {}
        });
        AlertDialog dialog = ui.dialog().setTitle("Приложения телефона").setView(form).setNegativeButton("Закрыть", null).show();
        dialog.setOnDismissListener(d -> { if (updateList == update) updateList = null; });
        list.setOnItemClickListener((parent, view, position, id) -> { AppRegistry.App app = (AppRegistry.App)view.getTag(); dialog.dismiss(); details(app); });
    }
    private void details(AppRegistry.App app) {
        ui.dialog().setTitle(app.label()).setItems(new String[]{"Открыть приложение", "Свои названия для голоса", "Как вызвать и что найдено"}, (dialog, choice) -> {
            if (choice == 0) new PhoneActionEngine(activity, message -> Toast.makeText(activity, message, Toast.LENGTH_LONG).show(), catalog, foreground).launchPhoneApp(app);
            if (choice == 1) {
                EditText input = ui.field("Одно название на строку"); input.setMinLines(3); input.setText(String.join("\n", app.aliases())); input.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE);
                AlertDialog editor = ui.dialog().setTitle("Названия: " + app.label()).setMessage("Например: «личная музыка» или «рабочие заметки». Используйте обычные русские слова, если распознаватель искажает иностранное имя. До 12 названий, по одному на строку.").setView(input).setNegativeButton("Отмена", null).setPositiveButton("Сохранить", null).show();
                editor.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
                    try {
                        List<String> aliases = AppRegistry.aliases(input.getText().toString()); editor.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(false);
                        catalog.saveAliases(app, aliases, saved -> {
                            if (!editor.isShowing()) return;
                            if (saved) { editor.dismiss(); show(""); }
                            else { editor.getButton(AlertDialog.BUTTON_POSITIVE).setEnabled(true); input.setError("Не удалось сохранить названия. Проверьте свободное место."); }
                        });
                    }
                    catch (IllegalArgumentException error) { input.setError(error.getMessage()); }
                });
            }
            if (choice == 2) ui.dialog().setTitle(app.label()).setMessage("Команда: «открой " + app.label() + "».\n\nСистемное название: " + app.label() + "\nПакет: " + app.packageName() + "\nАдрес запуска: " + app.activity() + "\nВаши названия: " + (app.aliases().isEmpty() ? "не заданы" : String.join(", ", app.aliases())) + "\n\nСканирование не переучивает словарь Vosk. Если имя распознаётся плохо, задайте название из известных русских слов. При одинаковых названиях WileyAI уточнит приложение.").setPositiveButton("Закрыть", null).show();
        }).setNegativeButton("Назад", (d, w) -> show("")).show();
    }
}
