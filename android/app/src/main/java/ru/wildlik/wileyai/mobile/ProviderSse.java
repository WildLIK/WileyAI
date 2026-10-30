package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.util.function.Consumer;

/** Bounded SSE without assuming providers emit numeric event IDs. No inference retries. */
public final class ProviderSse {
    public static void read(Reader source,Consumer<String> data)throws IOException{BufferedReader reader=new BufferedReader(source);StringBuilder line=new StringBuilder(),event=new StringBuilder();int c,total=0;while((c=reader.read())!=-1){if(++total>2*1024*1024)throw new IOException("Поток провайдера слишком большой");if(c!='\n'){if(c!='\r')line.append((char)c);if(line.length()>256*1024)throw new IOException("Событие провайдера слишком большое");continue;}String text=line.toString();line.setLength(0);if(text.isEmpty()){if(event.length()>0){data.accept(event.toString());event.setLength(0);}}else if(text.startsWith("data:")){if(event.length()>0)event.append('\n');event.append(text.substring(5).replaceFirst("^ ",""));if(event.length()>256*1024)throw new IOException("Событие провайдера слишком большое");}}if(line.length()>0||event.length()>0)throw new IOException("Поток оборвался внутри события");}
    private ProviderSse(){}
}
