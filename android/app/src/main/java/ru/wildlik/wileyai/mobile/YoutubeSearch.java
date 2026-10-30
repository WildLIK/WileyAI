package ru.wildlik.wileyai.mobile;

import android.os.*;
import android.net.Uri;
import org.json.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;

/** Public search page only: no account cookies, internal API, downloads or access to app screens. */
final class YoutubeSearch {
    record Video(String id, String title, String channel) {}
    private static final ExecutorService worker = Executors.newFixedThreadPool(2);
    static void find(String query, Consumer<List<Video>> done) {
        worker.execute(() -> {
            List<Video> videos = Collections.emptyList(); HttpURLConnection connection = null;
            try {
                Uri address=Uri.parse("https://www.youtube.com/results").buildUpon().appendQueryParameter("search_query",query).appendQueryParameter("hl","ru").build();
                connection=(HttpURLConnection)new URL(address.toString()).openConnection();
                connection.setConnectTimeout(8000);connection.setReadTimeout(8000);connection.setInstanceFollowRedirects(false);
                connection.setRequestProperty("User-Agent","Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36");
                connection.setRequestProperty("Accept-Language","ru,en;q=0.5");
                if(connection.getResponseCode()!=200)throw new IOException();
                try(InputStream input=connection.getInputStream();ByteArrayOutputStream bytes=new ByteArrayOutputStream()){
                    byte[] buffer=new byte[8192];int count;long began=SystemClock.elapsedRealtime();
                    while((count=input.read(buffer))!=-1){if(bytes.size()+count>4*1024*1024||SystemClock.elapsedRealtime()-began>15000)throw new IOException();bytes.write(buffer,0,count);}
                    videos=parse(bytes.toString(StandardCharsets.UTF_8.name()));
                }
            }catch(Exception unavailable){/* Consent/rate limits/page changes: caller opens the normal YouTube search. */}
            finally{if(connection!=null)connection.disconnect();}
            List<Video> result=videos;new Handler(Looper.getMainLooper()).post(()->done.accept(result));
        });
    }
    static List<Video> parse(String html)throws JSONException{
        int marker=html.indexOf("var ytInitialData = ");
        if(marker<0)marker=html.indexOf("ytInitialData = ");
        if(marker<0)return Collections.emptyList();
        int start=html.indexOf('{',marker),end=-1,depth=0;boolean string=false,escape=false;
        if(start<0)return Collections.emptyList();
        for(int i=start;i<html.length();i++){
            char c=html.charAt(i);if(string){if(escape)escape=false;else if(c=='\\')escape=true;else if(c=='"')string=false;continue;}
            if(c=='"')string=true;else if(c=='{')depth++;else if(c=='}'&&--depth==0){end=i+1;break;}
        }
        if(end<0)return Collections.emptyList();
        JSONObject root=new JSONObject(html.substring(start,end));Object content=root;
        JSONObject contents=root.optJSONObject("contents");
        if(contents!=null){JSONObject search=contents.optJSONObject("twoColumnSearchResultsRenderer");if(search!=null&&search.optJSONObject("primaryContents")!=null)content=search.getJSONObject("primaryContents");}
        List<Video> found=new ArrayList<>();walk(content,found,new HashSet<>(),0);return Collections.unmodifiableList(found);
    }
    private static void walk(Object value,List<Video> found,Set<String> ids,int depth)throws JSONException{
        if(depth>35||found.size()>=3)return;
        if(value instanceof JSONObject object){
            if(object.has("adSlotRenderer")||object.has("promotedSparklesWebRenderer")||object.has("promotedVideoRenderer"))return;
            JSONObject video=object.optJSONObject("videoRenderer");
            if(video!=null){String id=video.optString("videoId"),title=text(video.optJSONObject("title")),channel=text(video.optJSONObject("ownerText"));
                if(id.matches("[A-Za-z0-9_-]{11}")&&!title.isEmpty()&&ids.add(id))found.add(new Video(id,title,channel));return;}
            Iterator<String> keys=object.keys();while(keys.hasNext()&&found.size()<3){String key=keys.next();if(!key.toLowerCase(Locale.ROOT).contains("adplacement"))walk(object.opt(key),found,ids,depth+1);}
        }else if(value instanceof JSONArray array){for(int i=0;i<array.length()&&found.size()<3;i++)walk(array.opt(i),found,ids,depth+1);}
    }
    private static String text(JSONObject value){
        if(value==null)return "";StringBuilder result=new StringBuilder(value.optString("simpleText"));JSONArray runs=value.optJSONArray("runs");
        if(result.length()==0&&runs!=null)for(int i=0;i<runs.length();i++){JSONObject run=runs.optJSONObject(i);if(run!=null)result.append(run.optString("text"));}
        String clean=result.toString().replaceAll("[\\p{Cc}\\p{Cf}]"," ").trim();return clean.substring(0,Math.min(180,clean.length()));
    }
    private YoutubeSearch(){}
}
