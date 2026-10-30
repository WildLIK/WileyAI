import ru.wildlik.wileyai.mobile.*;

public final class MediaCommandsProbe {
    private static void is(String text,String kind,String value,String target){PhoneCommands.Action action=PhoneCommands.parse(text,true);if(action==null||!kind.equals(action.kind)||!value.equals(action.value)||!target.equals(action.target))throw new AssertionError(text+" -> "+(action==null?"null":action.kind+":"+action.value+":"+action.target));}
    private static void no(String text){if(PhoneCommands.parse(text,true)!=null)throw new AssertionError(text);}
    private static void check(boolean okay){if(!okay)throw new AssertionError();}
    public static void main(String[] args){
        switch(args[0]){
            case "transport":
                is("Пауза в Ютубе","media","pause","youtube");is("Ютуб, продолжи видео","media","play","youtube");is("поставь ютуб на паузу","media","pause","youtube");is("останови кион музыку","media","pause","music");is("продолжи музыку","media","play","music");is("следующее видео","media","next","youtube");is("предыдущая песня в КИОН Музыке","media","previous","music");is("какая песня играет","media","status","");is("какое видео в ютубе","media","status","youtube");break;
            case "routing":
                is("а время?","info","time","");is("а теперь какая сегодня дата?","info","date","");
                for(String time:new String[]{"время какое","время сколько сейчас","какое время","какое сейчас время","сколько сейчас время","который сейчас час","который час сейчас","скажи какое сейчас время","подскажи пожалуйста сколько времени","сейчас который час"})is(time,"info","time","");
                no("сколько времени нужно на дорогу");is("покажи видео какое время","media_search","какое время","youtube");
                is("Пауза в музыке на телефоне","media","pause","music");is("пожалуйста, продолжи в ютубе","media","play","youtube");is("громкость 50 в ютубе","volume","50","");is("Ютуб, сделай потише","volume","down","");no("пауза в ютубе на компьютере");no("пауза в ютубе в музыке");check(PhoneCommands.parse("пауза в ютубе",false)==null);break;
            case "search":
                is("найди песню Вальс цветов","media_search","Вальс цветов","music");is("включи трек Чайковский Вальс цветов в музыке","media_play_search","Чайковский Вальс цветов","music");is("найди видео про космос","media_search","про космос","youtube");is("включи на ютубе Big Buck Bunny","media_play_search","Big Buck Bunny","youtube");is("ютуб найди Кошки","media_search","Кошки","youtube");is("включи музыку","media","play","music");is("включи следующее видео","media","next","youtube");is("поставь песню на паузу","media","pause","");break;
            case "seek":
                is("перемотай видео вперед на тридцать секунд","media","seek:30000","youtube");is("перемотай назад на минуту в музыке","media","seek:-60000","music");is("перемотай на 2:30 в ютубе","media","position:150000","youtube");is("начни видео сначала","media","position:0","youtube");is("перемотай вперед на полминуты","media","seek:30000","");no("перемотай вперед на -5 секунд");no("перемотай вперед на 100000 минут");no("перемотай вперед на 10 секунд назад");no("перемотай на 2:99 в ютубе");break;
            case "reject":
                for(String text:new String[]{"не включи музыку","если скажу пауза в ютубе","например найди видео коты","расскажи как поставить видео на паузу","пауза\nв ютубе","«пауза в ютубе»","перемотай видео и удали чат"})no(text);break;
            case "conversation":
                check(ConversationMode.parse("давай поговорим")==ConversationMode.START);check(ConversationMode.parse("Окей, Вайли, давай поговорим")==ConversationMode.START);check(ConversationMode.parse("Закончили!")==ConversationMode.END);check(ConversationMode.parse("хватит разговаривать")==ConversationMode.END);check(ConversationMode.parse("не давай поговорим")==ConversationMode.NONE);check(ConversationMode.parse("если скажу закончили")==ConversationMode.NONE);check(ConversationMode.waitMillis(false,true,8,30,1,0)==8000);check(ConversationMode.waitMillis(true,false,8,30,2,100)==30000);check(ConversationMode.waitMillis(false,false,8,30,0,0)==0);check(ConversationMode.waitMillis(true,true,8,30,20,0)==0);check(ConversationMode.waitMillis(true,true,8,30,1,900000)==0);break;
            case "wake-conversation":
                check(WakePhrase.conversation(WakePhrase.DEFAULT,"Окей, Вайли, давай поговорим",1));check(WakePhrase.conversation(WakePhrase.DEFAULT,"окей вай ли давай поговорим",.8));check(!WakePhrase.conversation(WakePhrase.DEFAULT,"окей давай поговорим",1));check(!WakePhrase.conversation(WakePhrase.DEFAULT,"не окей вай ли давай поговорим",1));check(!WakePhrase.conversation(WakePhrase.DEFAULT,"окей вай ли давай поговорим",.74));check(!WakePhrase.matches(WakePhrase.DEFAULT,"окей вай ли давай поговорим",1));break;
            default:throw new AssertionError(args[0]);
        }
        System.out.println("passed: "+args[0]);
    }
}
