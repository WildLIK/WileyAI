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
    void render(LinearLayout cards,Runnable defaults,Runnable media,Runnable permissions) {
        ui.link(cards,"Все приложения","Каталог, поиск и ручные произношения",()->show(""));
        ui.link(cards,"Избранное","Приложения, которые вы отметили в каталоге",this::favorites);
        ui.link(cards,"Запомненные голосовые названия","Просмотр и изменение",this::remembered);
        ui.link(cards,"Приложения по умолчанию","Мессенджер, музыка и YouTube",defaults);
        ui.link(cards,"Управление плеерами","Музыка, YouTube и команды воспроизведения",media);
        ui.link(cards,"Статистика использования",PermissionPanel.usageAllowed(activity)?"Android · время на экране за 7 дней":"Требуется доступ Android",
            ()->{if(PermissionPanel.usageAllowed(activity))usage();else permissions.run();});
        LinearLayout info = ui.disclosure(cards, "Каталог и проверка запусков");
        status = ui.text(catalog.status(),14,ui.theme.accentText);
        info.addView(status);
        refresh=ui.button("Обновить список приложений",catalog::refresh);
        info.addView(refresh);
        refresh();
        info.addView(ui.text("Автоматическое запоминание названия после выбора требует подтверждённого запуска и доступа к статистике Android.",14,ui.theme.secondary));
        info.addView(ui.text("Читаются системные названия и адреса запуска в текущем профиле Android. Список и ваши псевдонимы остаются на телефоне. При совпадении названий WileyAI уточнит выбор.", 14, ui.theme.secondary));
    }
    void renderDefaults(LinearLayout parent){
        addDefault(parent,"Мессенджер","messenger");
        addDefault(parent,"Музыка","music");
        addDefault(parent,"YouTube","video");
    }
    private void addDefault(LinearLayout parent,String label,String role){
        Button preferred=ui.button(label+": "+catalog.preferredLabel(role),()->{});
        preferred.setOnClickListener(v->chooseRole(role,()->preferred.setText(label+": "+catalog.preferredLabel(role))));
        parent.addView(preferred);
    }
    private boolean favorite(AppRegistry.App app){
        return activity.getSharedPreferences("wiley-mobile",0).getStringSet("favorite_apps",Set.of()).contains(app.id());
    }
    private void toggleFavorite(AppRegistry.App app){
        var prefs=activity.getSharedPreferences("wiley-mobile",0);
        var ids=new HashSet<>(prefs.getStringSet("favorite_apps",Set.of()));
        if(!ids.remove(app.id()))ids.add(app.id());
        prefs.edit().putStringSet("favorite_apps",ids).apply();
    }
    private void favorites(){
        var apps=catalog.entries().stream().filter(this::favorite).toArray(AppRegistry.App[]::new);
        var dialog=ui.dialog().setTitle("Избранные приложения");
        if(apps.length==0)dialog.setMessage("Откройте «Все приложения» и добавьте нужные приложения в избранное.");
        else dialog.setItems(Arrays.stream(apps).map(AppRegistry.App::label).toArray(String[]::new),(d,index)->details(apps[index]));
        dialog.setNegativeButton("Закрыть",null).show();
    }
    private void usage(){
        long now=System.currentTimeMillis();
        var manager=activity.getSystemService(android.app.usage.UsageStatsManager.class);
        var stats=manager.queryAndAggregateUsageStats(now-7L*24*60*60*1000,now);
        Map<String,String> labels=new HashMap<>();
        for(var app:catalog.entries())labels.putIfAbsent(app.packageName(),app.label());
        String[] lines=stats.values().stream()
            .filter(item->labels.containsKey(item.getPackageName())&&item.getTotalTimeInForeground()>0)
            .sorted(Comparator.comparingLong(android.app.usage.UsageStats::getTotalTimeInForeground).reversed())
            .limit(10)
            .map(item->labels.get(item.getPackageName())+" · "+(item.getTotalTimeInForeground()/60000)+" мин")
            .toArray(String[]::new);
        var dialog=ui.dialog().setTitle("Время на экране за 7 дней");
        if(lines.length==0)dialog.setMessage("Android пока не вернул статистику установленных приложений.");
        else dialog.setItems(lines,null);
        dialog.setPositiveButton("Закрыть",null).show();
    }
    private void remembered(){
        AppNameMemory memory=catalog.nameMemory();Map<String,String> values=memory.entries();List<String> names=new ArrayList<>(values.keySet());String[] rows=new String[names.size()];for(int i=0;i<rows.length;i++)rows[i]=names.get(i)+" → "+values.get(names.get(i));
        AlertDialog.Builder builder=ui.dialog().setTitle("Запомненные названия");
        if(rows.length==0)builder.setMessage("Пока нет подтверждённых соответствий.");else builder.setItems(rows,(d,index)->{
            String name=names.get(index);ui.dialog().setTitle(name).setItems(new String[]{"Изменить название","Удалить"},(x,which)->{
                if(which==1){memory.remove(name);remembered();return;}
                EditText input=ui.field("Название для голоса");input.setText(name);ui.dialog().setTitle("Изменить название").setView(input).setNegativeButton("Отмена",null).setPositiveButton("Сохранить",(dialog,button)->{if(!memory.rename(name,input.getText().toString()))Toast.makeText(activity,"Название занято или недопустимо",Toast.LENGTH_LONG).show();remembered();}).show();
            }).setNegativeButton("Назад",(x,w)->remembered()).show();
        });
        builder.setNegativeButton("Закрыть",null);if(rows.length>0)builder.setNeutralButton("Очистить",(d,w)->ui.dialog().setTitle("Удалить запомненные названия?").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(x,y)->{memory.clear();remembered();}).show());builder.show();
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
        ui.dialog().setTitle(app.label()).setItems(new String[]{"Открыть приложение", "Свои названия для голоса", "Как вызвать и что найдено",
            favorite(app)?"Убрать из избранного":"Добавить в избранное"}, (dialog, choice) -> {
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
            if(choice==3){toggleFavorite(app);details(app);}
        }).setNegativeButton("Назад", (d, w) -> show("")).show();
    }
}
