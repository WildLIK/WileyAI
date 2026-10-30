package ru.wildlik.wileyai.mobile;

import java.util.*;
import java.time.*;

/** Provider-independent allowlist and validator. It contains no Android execution or network code. */
public final class AndroidTools {
    public enum Risk { SAFE_READ, DEVICE_ACTION, PERSONAL }
    public record Field(String type,boolean required,int min,int max,List<String> values){}
    public record Tool(String name,String description,Risk risk,Map<String,Field> fields){}
    public record Call(String tool,Map<String,Object> arguments){}
    public record Plan(List<Call> steps,String reply){}
    public record Result(String tool,String status,String summary,Map<String,Object> data){
        public boolean success(){return status.equals("verified")||status.equals("requested");}
    }
    private static Field str(boolean required,int max){return new Field("string",required,1,max,List.of());}
    private static Field number(boolean required,int min,int max){return new Field("integer",required,min,max,List.of());}
    private static Field choice(boolean required,String... values){return new Field("string",required,1,40,List.of(values));}
    private static Map<String,Field> fields(Object... pairs){Map<String,Field> result=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2)result.put((String)pairs[i],(Field)pairs[i+1]);return Collections.unmodifiableMap(result);}
    private static final Map<String,Tool> REGISTRY=new LinkedHashMap<>();
    static{
        add("list_installed_apps","Названия доступных приложений",Risk.PERSONAL,fields());
        add("find_app","Найти приложение по названию",Risk.PERSONAL,fields("app_name",str(true,100)));
        add("open_app","Открыть установленное приложение",Risk.DEVICE_ACTION,fields("app_name",str(true,100)));
        add("get_foreground_app","Последнее активное приложение за 10 минут; история за вчера недоступна; нужен доступ к статистике",Risk.PERSONAL,fields());
        Map<String,String> mediaLabels=Map.of("play","продолжить","pause","пауза","next","следующий трек","previous","предыдущий трек");
        for(String verb:List.of("play","pause","next","previous"))add("media_"+verb,"Команда выбранному плееру: "+mediaLabels.get(verb),Risk.DEVICE_ACTION,fields("target",choice(false,"music","youtube","active")));
        add("media_get_state","Проверить состояние выбранного плеера",Risk.PERSONAL,fields("target",choice(false,"music","youtube","active")));
        add("media_search","Поиск в выбранном плеере; запуск не гарантирован",Risk.DEVICE_ACTION,fields("query",str(true,200),"target",choice(true,"music","youtube")));
        add("media_set_volume","Установить громкость музыки, проценты 0–100",Risk.DEVICE_ACTION,fields("percent",number(true,0,100)));
        add("set_volume","Установить громкость музыки, проценты 0–100",Risk.DEVICE_ACTION,fields("percent",number(true,0,100)));
        add("get_volume","Текущая громкость музыки",Risk.SAFE_READ,fields());
        add("adjust_volume","Сделать музыку тише или громче",Risk.DEVICE_ACTION,fields("direction",choice(true,"up","down"),"percent",number(false,1,50)));
        add("get_battery_status","Уровень батареи",Risk.SAFE_READ,fields());
        add("get_device_information","Модель устройства и версия Android; без идентификаторов",Risk.SAFE_READ,fields());
        add("get_network_status","Состояние подключения; без SSID и IP",Risk.SAFE_READ,fields());
        add("get_time","Текущее время Android",Risk.SAFE_READ,fields());
        add("get_date","Текущая дата Android",Risk.SAFE_READ,fields());
        add("open_wifi_settings","Открыть настройки Wi-Fi",Risk.DEVICE_ACTION,fields());
        add("open_bluetooth_settings","Открыть настройки Bluetooth",Risk.DEVICE_ACTION,fields());
        add("open_app_settings","Открыть настройки найденного приложения",Risk.DEVICE_ACTION,fields("app_name",str(true,100)));
        add("create_alarm","Открыть создание будильника в приложении часов",Risk.PERSONAL,fields("hour",number(true,0,23),"minute",number(true,0,59),"label",str(false,100)));
        add("create_reminder","Локальное напоминание; day=today/tomorrow/ГГГГ-ММ-ДД, time=ЧЧ:ММ",Risk.PERSONAL,fields("text",str(true,300),"day",str(true,10),"time",str(true,5)));
        add("list_reminders","Прочитать до 20 напоминаний WileyAI",Risk.PERSONAL,fields());
        add("create_note","Сохранить локальную заметку WileyAI",Risk.PERSONAL,fields("text",str(true,2000)));
        add("open_calendar","Открыть календарь; без чтения событий",Risk.DEVICE_ACTION,fields());
        add("web_search","Открыть поиск в браузере; не читает результаты",Risk.DEVICE_ACTION,fields("query",str(true,200)));
        add("get_weather","Погода Open-Meteo по указанному городу",Risk.SAFE_READ,fields("city",str(true,100)));
    }
    private static void add(String name,String description,Risk risk,Map<String,Field> fields){REGISTRY.put(name,new Tool(name,description,risk,fields));}
    public static Collection<Tool> all(){return Collections.unmodifiableCollection(REGISTRY.values());}
    public static Tool get(String name){Tool tool=REGISTRY.get(name);if(tool==null)throw new IllegalArgumentException("Неизвестный инструмент: "+name);return tool;}
    public static Call validate(String name,Map<?,?> arguments){Tool tool=get(name);if(arguments==null)throw new IllegalArgumentException("Нет аргументов");Map<String,Object> clean=new LinkedHashMap<>();
        for(Object key:arguments.keySet())if(!(key instanceof String)||!tool.fields.containsKey(key))throw new IllegalArgumentException("Неизвестный аргумент инструмента");
        for(var entry:tool.fields.entrySet()){Field field=entry.getValue();Object value=arguments.get(entry.getKey());if(value==null){if(field.required)throw new IllegalArgumentException("Не заполнено: "+entry.getKey());continue;}
            if(field.type.equals("integer")){if(!(value instanceof Long||value instanceof Integer)||((Number)value).longValue()<field.min||((Number)value).longValue()>field.max)throw new IllegalArgumentException("Число вне допустимого диапазона");clean.put(entry.getKey(),((Number)value).intValue());}
            else{if(!(value instanceof String text)||text.trim().length()<field.min||text.length()>field.max||text.codePoints().anyMatch(c->Character.isISOControl(c)||c==0x202e||c==0x202d))throw new IllegalArgumentException("Некорректный текст аргумента");if(!field.values.isEmpty()&&!field.values.contains(text))throw new IllegalArgumentException("Недопустимое значение аргумента");clean.put(entry.getKey(),text.trim());}
        }
        if(name.equals("create_reminder")){String day=(String)clean.get("day"),time=(String)clean.get("time");if(!day.matches("today|tomorrow|[0-9]{4}-[0-9]{2}-[0-9]{2}")||!time.matches("[0-9]{2}:[0-9]{2}"))throw new IllegalArgumentException("Напоминанию нужны дата и точное время");LocalTime.parse(time);if(!day.equals("today")&&!day.equals("tomorrow"))LocalDate.parse(day);}
        return new Call(name,Collections.unmodifiableMap(clean));
    }
    public static Plan parse(String json){Object root=StrictJson.parse(json);if(!(root instanceof Map<?,?> map)||!map.keySet().stream().allMatch(key->key.equals("steps")||key.equals("reply"))||!(map.get("steps") instanceof List<?> steps)||steps.size()>4)throw new IllegalArgumentException("Нужен план не более четырёх шагов");
        Object reply=map.getOrDefault("reply",null);if(reply!=null&&(!(reply instanceof String)||((String)reply).length()>2000))throw new IllegalArgumentException("Некорректный текст ответа");List<Call> result=new ArrayList<>();
        for(Object item:steps){if(!(item instanceof Map<?,?> call)||call.size()!=2||!(call.get("tool") instanceof String name)||!(call.get("arguments") instanceof Map<?,?> args))throw new IllegalArgumentException("Некорректный шаг плана");result.add(validate(name,args));}
        return new Plan(List.copyOf(result),reply==null?"":(String)reply);
    }
    public static long reminderTime(Call call,ZonedDateTime now){String day=(String)call.arguments.get("day");LocalDate date=day.equals("today")?now.toLocalDate():day.equals("tomorrow")?now.toLocalDate().plusDays(1):LocalDate.parse(day);LocalDateTime local=LocalDateTime.of(date,LocalTime.parse((String)call.arguments.get("time")));if(now.getZone().getRules().getValidOffsets(local).size()!=1)throw new IllegalArgumentException("Уточните время при переводе часов");long epoch=local.atZone(now.getZone()).toInstant().toEpochMilli();if(epoch<now.toInstant().toEpochMilli()+5000||epoch>now.plusYears(1).toInstant().toEpochMilli())throw new IllegalArgumentException("Напоминание должно быть в течение будущего года");return epoch;}
    public static String preview(Plan plan){List<String> lines=new ArrayList<>();for(Call call:plan.steps){Map<String,Object> args=call.arguments;String text=get(call.tool).description;switch(call.tool){case "open_app"->text="Открыть «"+args.get("app_name")+"»";case "find_app"->text="Найти приложение «"+args.get("app_name")+"»";case "open_app_settings"->text="Открыть настройки «"+args.get("app_name")+"»";case "set_volume","media_set_volume"->text="Громкость музыки: "+args.get("percent")+"% максимума";case "create_note"->text="Сохранить заметку: "+args.get("text");case "create_reminder"->text="Напомнить "+args.get("day")+" в "+args.get("time")+": "+args.get("text");case "create_alarm"->text=String.format(Locale.ROOT,"Создать будильник на %02d:%02d через приложение часов",args.get("hour"),args.get("minute"));case "media_search"->text="Поиск в "+(args.get("target").equals("youtube")?"YouTube":"музыке")+": "+args.get("query");case "web_search"->text="Открыть поиск: "+args.get("query");case "get_weather"->text="Погода: "+args.get("city");}lines.add(text);}return String.join("\n",lines);}
    private AndroidTools(){}
}
