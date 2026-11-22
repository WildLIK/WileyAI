package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.text.InputFilter;
import android.text.InputType;
import android.widget.EditText;
import android.widget.LinearLayout;

final class PersonalPanel {
    private final Activity activity;
    private final MobileUi ui;
    private final PersonalPreferences preferences;

    PersonalPanel(Activity activity,MobileUi ui){
        this.activity=activity;
        this.ui=ui;
        preferences=new PersonalPreferences(activity);
    }

    void profile(LinearLayout parent){
        EditText name=input(parent,"Ваше имя",preferences.name(),80,false);
        EditText address=input(parent,"Как к вам обращаться",preferences.address(),80,false);
        EditText general=input(parent,"Основные предпочтения",preferences.preferences(),350,true);
        parent.addView(ui.button("Сохранить профиль",()->{
            preferences.profile(name.getText().toString(),address.getText().toString(),general.getText().toString());
            saved();
        }));
        localOnly(parent);
    }

    void communication(LinearLayout parent){
        EditText instructions=input(parent,"Например, отвечай кратко и на «ты»",preferences.instructions(),600,true);
        var enabled=ui.setting(parent,"Учитывать пожелания о стиле",preferences.instructionsEnabled(),
            on->preferences.communication(preferences.instructions(),on));
        parent.addView(ui.button("Сохранить инструкции",()->{
            preferences.communication(instructions.getText().toString(),enabled.isChecked());
            saved();
        }));
        localOnly(parent);
    }

    private void localOnly(LinearLayout parent){
        parent.addView(ui.text("Используется в текстовых ответах локальной модели. Данные хранятся на телефоне.",14,ui.theme.secondary));
    }

    void memory(LinearLayout parent){
        ui.setting(parent,"Учитывать последние воспоминания в локальных ответах",preferences.memoryEnabled(),preferences::memoryEnabled);
        parent.addView(ui.text("Записи создаются вручную. История чатов не добавляется в память.",14,ui.theme.secondary));
        parent.addView(ui.button("Добавить воспоминание",()->editMemory(null,parent)));
        LinearLayout records=ui.vertical();
        parent.addView(records);
        try {
            var entries=preferences.memories();
            if(entries.isEmpty())records.addView(ui.text("Пока нет записей.",14,ui.theme.secondary));
            for(int i=entries.size()-1;i>=0;i--){
                var entry=entries.get(i);
                String label=entry.text().replaceAll("\\s+"," ");
                if(label.length()>100)label=label.substring(0,100)+"…";
                ui.link(records,label,"Открыть запись",()->editMemory(entry,parent));
            }
        }catch(IllegalStateException invalid){
            records.addView(ui.text("Не удалось прочитать сохранённые записи.",14,ui.theme.secondary));
        }
    }

    private void editMemory(PersonalPreferences.Memory entry,LinearLayout parent){
        LinearLayout form=ui.vertical();
        ui.padded(form,8);
        EditText editor=input(form,"Подтверждённый факт или предпочтение",entry==null?"":entry.text(),400,true);
        var builder=ui.dialog().setTitle(entry==null?"Новое воспоминание":"Воспоминание").setView(form)
            .setNegativeButton("Отмена",null).setPositiveButton("Сохранить",null);
        if(entry!=null)builder.setNeutralButton("Удалить",(d,w)->ui.dialog().setTitle("Удалить воспоминание?")
            .setNegativeButton("Отмена",null).setPositiveButton("Удалить",(confirm,which)->{
                try{
                    preferences.removeMemory(entry.id());
                    refreshMemory(parent);
                }catch(IllegalStateException invalid){
                    android.widget.Toast.makeText(activity,invalid.getMessage(),android.widget.Toast.LENGTH_LONG).show();
                }
            }).show());
        var dialog=builder.show();
        dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            String value=editor.getText().toString().trim();
            if(value.isEmpty()){editor.setError("Введите текст");return;}
            try{
                preferences.saveMemory(entry==null?null:entry.id(),value);
                dialog.dismiss();
                refreshMemory(parent);
            }catch(IllegalStateException invalid){editor.setError(invalid.getMessage());}
        });
    }

    private void refreshMemory(LinearLayout parent){
        parent.removeAllViews();
        memory(parent);
    }

    private EditText input(LinearLayout parent,String label,String value,int max,boolean multiline){
        var caption=ui.text(label,14,ui.theme.secondary);
        caption.setPadding(ui.dp(4),ui.dp(10),0,ui.dp(4));
        parent.addView(caption);
        EditText field=ui.field(label);
        field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(max)});
        if(multiline){
            field.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_MULTI_LINE|InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            field.setMinLines(2);
        }else field.setSingleLine(true);
        field.setText(value);
        parent.addView(field);
        return field;
    }

    private void saved(){android.widget.Toast.makeText(activity,"Сохранено",android.widget.Toast.LENGTH_SHORT).show();}

}
