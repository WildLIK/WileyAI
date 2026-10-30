package ru.wildlik.wileyai.mobile;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;

/** JDK-only HTTPS/SSE transport, also exercised by host integration tests. No cookies or redirects. */
public final class GatewayWire {
    public record Reply(int status, String body) {}
    public record Event(long id, String type, String data) {}
    private final URI base;
    private final String token;
    interface ConnectionFactory { HttpURLConnection open(URL url) throws IOException; }
    private final ConnectionFactory connections;
    private volatile HttpURLConnection active;
    private volatile boolean cancelled;
    public GatewayWire(String address,String token) throws IOException {this(address,token,false);}
    public GatewayWire(String address,String token,boolean loopbackTest) throws IOException {
        this(address,token,loopbackTest,url->(HttpURLConnection)url.openConnection());
    }
    GatewayWire(String address,String token,ConnectionFactory connections)throws IOException{this(address,token,false,connections);}
    private GatewayWire(String address,String token,boolean loopbackTest,ConnectionFactory connections) throws IOException {
        try {
            base=new URI(address);
            boolean local=loopbackTest&&"http".equals(base.getScheme())&&"127.0.0.1".equals(base.getHost());
            if((!"https".equalsIgnoreCase(base.getScheme())&&!local)||base.getHost()==null||base.getUserInfo()!=null||base.getQuery()!=null||base.getFragment()!=null||base.getPort()==0||base.getPort()>65535||(!base.getPath().isEmpty()&&!base.getPath().equals("/")))throw new IOException("Нужен HTTPS-адрес своего Gateway без дополнительных путей и параметров.");
            if(token==null||!token.matches("[A-Za-z0-9_-]{20,150}"))throw new IOException("Проверьте токен WileyAI Gateway.");
            this.token=token;
            this.connections=connections;
        }catch(URISyntaxException error){throw new IOException("Некорректный адрес Gateway.");}
    }
    private HttpURLConnection open(String path,String method)throws IOException{
        if(cancelled)throw new InterruptedIOException("Отменено");
        if(!path.startsWith("/api/v1/")||path.contains("..")||path.contains("\\")||path.contains("#"))throw new IOException("Некорректный путь Gateway.");
        HttpURLConnection connection=connections.open(base.resolve(path).toURL());active=connection;
        connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(12000);connection.setReadTimeout(25000);connection.setRequestMethod(method);
        connection.setRequestProperty("Authorization","Bearer "+token);connection.setRequestProperty("Accept","application/json");return connection;
    }
    public Reply request(String method,String path,String body)throws IOException{
        return upload(method,path,body==null?null:body.getBytes(StandardCharsets.UTF_8),"application/json; charset=utf-8",null);
    }
    public Reply upload(String method,String path,byte[] bytes,String mime,String filename)throws IOException{
        HttpURLConnection connection=open(path,method);
        try{
            if(bytes!=null){connection.setDoOutput(true);connection.setRequestProperty("Content-Type",mime);if(filename!=null)connection.setRequestProperty("X-File-Name",URLEncoder.encode(filename,"UTF-8").replace("+","%20"));connection.setFixedLengthStreamingMode(bytes.length);try(OutputStream output=connection.getOutputStream()){output.write(bytes);}}
            int status=connection.getResponseCode();InputStream input=status>=400?connection.getErrorStream():connection.getInputStream();
            String text="";if(input!=null)try(InputStream stream=input;ByteArrayOutputStream result=new ByteArrayOutputStream()){byte[] buffer=new byte[8192];int count;while((count=stream.read(buffer))!=-1){if(result.size()+count>8*1024*1024)throw new IOException("Ответ Gateway слишком большой.");result.write(buffer,0,count);}text=result.toString("UTF-8");}
            return new Reply(status,text);
        }finally{connection.disconnect();if(active==connection)active=null;}
    }
    public long events(String run,long after,Consumer<Event> consumer)throws IOException{
        if(!run.matches("[a-f0-9]{32}"))throw new IOException("Некорректный запрос Gateway.");
        HttpURLConnection connection=open("/api/v1/runs/"+run+"/events?after="+after,"GET");
        connection.setRequestProperty("Accept","text/event-stream");connection.setRequestProperty("Last-Event-ID",Long.toString(after));
        try{
            if(connection.getResponseCode()!=200)throw new IOException("Поток Gateway недоступен. Проверьте подключение.");
            try(Reader reader=new InputStreamReader(connection.getInputStream(),StandardCharsets.UTF_8)){
                return readEvents(reader,after,consumer);
            }
        }finally{connection.disconnect();if(active==connection)active=null;}
    }
    public static long readEvents(Reader source,long after,Consumer<Event> consumer)throws IOException{
        BufferedReader reader=new BufferedReader(source);long cursor=after,id=0;String type="message";StringBuilder data=new StringBuilder();
        StringBuilder line=new StringBuilder();int character;
        while((character=reader.read())!=-1){
            if(character!='\n'){if(character!='\r')line.append((char)character);if(line.length()>256*1024)throw new IOException("Событие Gateway слишком большое.");continue;}
            String value=line.toString();line.setLength(0);
            if(value.isEmpty()){
                if(data.length()>0){if(id<=0)throw new IOException("Нет номера события Gateway.");if(id>cursor){consumer.accept(new Event(id,type,data.toString()));cursor=id;if(type.matches("run\\.(?:completed|failed|cancelled|interrupted)"))return cursor;}}
                id=0;type="message";data.setLength(0);continue;
            }
            if(value.startsWith(":"))continue;
            int separator=value.indexOf(':');String field=separator<0?value:value.substring(0,separator),part=separator<0?"":value.substring(separator+1).replaceFirst("^ ","");
            if(field.equals("id")){try{id=Long.parseLong(part);}catch(NumberFormatException error){throw new IOException("Некорректный номер события Gateway.");}}
            else if(field.equals("event"))type=part;
            else if(field.equals("data")){if(data.length()>0)data.append('\n');data.append(part);if(data.length()>256*1024)throw new IOException("Событие Gateway слишком большое.");}
        }
        return cursor;
    }
    public void cancel(){cancelled=true;HttpURLConnection connection=active;if(connection!=null)connection.disconnect();}
}
