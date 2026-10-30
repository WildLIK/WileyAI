package ru.wildlik.wileyai.mobile;

import java.util.*;

/** Small strict JSON decoder for untrusted model output. No duplicate keys, comments or trailing text. */
public final class StrictJson {
    private final String text;private int at;
    private StrictJson(String text){this.text=text;}
    public static Object parse(String text){if(text==null||text.length()>16384)throw new IllegalArgumentException("Ответ модели слишком большой");StrictJson parser=new StrictJson(text);Object value=parser.value(0);parser.space();if(parser.at!=text.length())throw parser.bad();return value;}
    private IllegalArgumentException bad(){return new IllegalArgumentException("Модель вернула некорректный JSON");}
    private void space(){while(at<text.length()&&" \t\r\n".indexOf(text.charAt(at))>=0)at++;}
    private char take(){if(at>=text.length())throw bad();return text.charAt(at++);}
    private Object value(int depth){space();if(depth>12||at>=text.length())throw bad();char c=text.charAt(at);
        if(c=='{'){at++;Map<String,Object> result=new LinkedHashMap<>();space();if(at<text.length()&&text.charAt(at)=='}'){at++;return result;}while(true){space();if(at>=text.length()||text.charAt(at)!='"')throw bad();String key=string();space();if(take()!=':'||result.containsKey(key))throw bad();result.put(key,value(depth+1));space();char end=take();if(end=='}')return result;if(end!=',')throw bad();}}
        if(c=='['){at++;List<Object> result=new ArrayList<>();space();if(at<text.length()&&text.charAt(at)==']'){at++;return result;}while(true){if(result.size()>=100)throw bad();result.add(value(depth+1));space();char end=take();if(end==']')return result;if(end!=',')throw bad();}}
        if(c=='"')return string();for(String word:new String[]{"true","false","null"})if(text.startsWith(word,at)){at+=word.length();return word.equals("null")?null:word.equals("true");}
        int start=at;while(at<text.length()&&"-+0123456789.eE".indexOf(text.charAt(at))>=0)at++;String number=text.substring(start,at);if(!number.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"))throw bad();try{if(!number.contains(".")&&!number.contains("e")&&!number.contains("E"))return Long.parseLong(number);double n=Double.parseDouble(number);if(!Double.isFinite(n))throw bad();return n;}catch(NumberFormatException error){throw bad();}
    }
    private String string(){if(take()!='"')throw bad();StringBuilder out=new StringBuilder();while(true){char c=take();if(c=='"')break;if(c<32)throw bad();if(c=='\\'){c=take();switch(c){case '"':case '\\':case '/':out.append(c);break;case 'b':out.append('\b');break;case 'f':out.append('\f');break;case 'n':out.append('\n');break;case 'r':out.append('\r');break;case 't':out.append('\t');break;case 'u':if(at+4>text.length())throw bad();try{out.append((char)Integer.parseInt(text.substring(at,at+4),16));}catch(NumberFormatException error){throw bad();}at+=4;break;default:throw bad();}}else out.append(c);}
        for(int i=0;i<out.length();i++)if(Character.isSurrogate(out.charAt(i))){if(!Character.isHighSurrogate(out.charAt(i))||i+1>=out.length()||!Character.isLowSurrogate(out.charAt(++i)))throw bad();}return out.toString();
    }
}
