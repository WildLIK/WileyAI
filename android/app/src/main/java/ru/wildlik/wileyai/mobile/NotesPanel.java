package ru.wildlik.wileyai.mobile;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.database.Cursor;
import android.text.Editable;
import android.text.TextWatcher;
import android.widget.*;

/** UI over the same local database used by the model tools. */
final class NotesPanel {
 private final Activity activity; private final MobileUi ui; private LinearLayout list; private String query="";
 NotesPanel(Activity activity, MobileUi ui){this.activity=activity;this.ui=ui;}
 void render(LinearLayout parent){
  parent.addView(ui.button("+ Новая заметка",()->editor(null,"")));
  EditText search=ui.field("Поиск по заметкам"); parent.addView(search);
  list=ui.vertical(); parent.addView(list);
  search.addTextChangedListener(new TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){} public void onTextChanged(CharSequence s,int start,int before,int count){query=s.toString();refresh();} public void afterTextChanged(Editable e){} }); refresh();
 }
 private void refresh(){list.removeAllViews(); int count=0; try(ToolsData data=new ToolsData(activity);Cursor c=data.getReadableDatabase().rawQuery("SELECT id,text,created FROM notes ORDER BY created DESC",null)){
  while(c.moveToNext()){String id=c.getString(0),text=c.getString(1);long created=c.getLong(2);if(!NotePresentation.matches(text,query))continue;count++;
   LinearLayout card=ui.vertical();card.setPadding(ui.dp(12),ui.dp(8),ui.dp(12),ui.dp(8));card.setBackground(ui.panel(ui.theme.low,14));
   LinearLayout line=ui.row(); TextView title=ui.text(NotePresentation.title(text),16,ui.theme.accentText);title.setMaxLines(1);title.setEllipsize(android.text.TextUtils.TruncateAt.END);line.addView(title,new LinearLayout.LayoutParams(0,-2,1));Button more=ui.button("⋮",()->actions(id,text));more.setContentDescription("Действия с заметкой");line.addView(more,new LinearLayout.LayoutParams(ui.dp(48),ui.dp(48)));card.addView(line);
   TextView preview=ui.text(text,14,ui.theme.secondary);preview.setMaxLines(3);preview.setEllipsize(android.text.TextUtils.TruncateAt.END);card.addView(preview);card.addView(ui.text("Создано · "+android.text.format.DateFormat.format("dd.MM.yyyy HH:mm",created),12,ui.theme.muted));card.setOnClickListener(v->view(id,text));LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.setMargins(0,ui.dp(4),0,ui.dp(4));list.addView(card,p);
  }
 } if(count==0)list.addView(ui.text(query.isBlank()?"Заметок пока нет.":"Ничего не найдено.",14,ui.theme.secondary)); }
 private void actions(String id,String text){ui.dialog().setTitle("Заметка").setItems(new String[]{"Открыть","Редактировать","Копировать","Удалить"},(d,n)->{if(n==0)view(id,text);else if(n==1)editor(id,text);else if(n==2)copy(text);else delete(id);}).setNegativeButton("Отмена",null).show();}
 private void view(String id,String value){TextView text=ui.text(value,16,ui.theme.text);text.setTextIsSelectable(true);text.setAutoLinkMask(android.text.util.Linkify.WEB_URLS);ScrollView scroll=new ScrollView(activity);scroll.setPadding(ui.dp(16),ui.dp(8),ui.dp(16),ui.dp(8));scroll.addView(text);ui.dialog().setTitle(NotePresentation.title(value)).setView(scroll).setNeutralButton("Копировать",(d,w)->copy(value)).setNegativeButton("Закрыть",null).setPositiveButton("Изменить",(d,w)->editor(id,value)).show();}
 private void copy(String value){((ClipboardManager)activity.getSystemService(Context.CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Заметка WileyAI",value));Toast.makeText(activity,"Скопировано",Toast.LENGTH_SHORT).show();}
 private void editor(String id,String value){EditText text=ui.field("Текст заметки");text.setSingleLine(false);text.setMinLines(5);text.setText(value);ui.dialog().setTitle(id==null?"Новая заметка":"Редактировать заметку").setView(text).setNegativeButton("Отмена",null).setPositiveButton("Сохранить",(d,w)->{String content=text.getText().toString();if(content.isBlank()){Toast.makeText(activity,"Заметка пуста",Toast.LENGTH_SHORT).show();return;}try(ToolsData data=new ToolsData(activity)){if(id==null)data.note(content);else {android.content.ContentValues row=new android.content.ContentValues();row.put("text",content);if(data.getWritableDatabase().update("notes",row,"id=?",new String[]{id})!=1){Toast.makeText(activity,"Заметка уже удалена",Toast.LENGTH_SHORT).show();return;}}}refresh();}).show();}
 private void delete(String id){ui.dialog().setTitle("Удалить заметку?").setMessage("Это действие нельзя отменить.").setNegativeButton("Отмена",null).setPositiveButton("Удалить",(d,w)->{try(ToolsData data=new ToolsData(activity)){data.getWritableDatabase().delete("notes","id=?",new String[]{id});}refresh();}).show();}
}
