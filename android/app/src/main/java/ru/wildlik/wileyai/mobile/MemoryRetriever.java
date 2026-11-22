package ru.wildlik.wileyai.mobile;

import java.util.*;

/** Small lexical retrieval. A result must share a meaningful term with the query. */
final class MemoryRetriever {
    record Candidate(String text, boolean important, String category) {}
    private static final Set<String> STOP=Set.of("что","как","какой","какая","какое","какие","меня","мне","мои","моя","моей","мое","мой","помнишь","помнишься","расскажи","предпочитаю","предпочитаешь","люблю","любимый","любимая","пользуюсь","какого","этот","это","the","what","about","my","you","and","are");
    private static Set<String> terms(String value){
        Set<String> terms=new HashSet<>();
        for(String word:value.toLowerCase(Locale.ROOT).replace('ё','е').split("[^\\p{L}\\p{N}]+")){
            if(word.length()<3||STOP.contains(word))continue;
            String stem=word;
            if(word.matches("[а-я]+")&&word.length()>4){
                stem=word.replaceFirst("(иями|ами|ями|ого|ему|ыми|ими|ах|ях|ом|ем|ий|ый|ая|ое|ие|ую|ые|а|я|ы|и|у|е)$", "");
                if(stem.length()<3)stem=word;
            }
            terms.add(stem);
        }
        return terms;
    }
    static List<Candidate> select(String request,List<Candidate> entries,int limit,int maxChars){
        Set<String> query=terms(request);if(query.isEmpty())return List.of();
        record Scored(Candidate item,int score,int index){}
        List<Scored> scored=new ArrayList<>();int index=0;
        for(Candidate entry:entries){
            Set<String> tokens=terms(entry.text());int overlap=0;
            for(String term:query){
                boolean match=tokens.contains(term);
                if(!match&&term.length()>=5)for(String token:tokens)if(token.length()>=5&&token.substring(0,5).equals(term.substring(0,5))){match=true;break;}
                if(match)overlap++;
            }
            if(overlap>0)scored.add(new Scored(entry,overlap*10+(entry.important()?2:0),index));
            index++;
        }
        scored.sort(Comparator.comparingInt(Scored::score).reversed().thenComparingInt(Scored::index));
        List<Candidate> result=new ArrayList<>();Set<String> seen=new HashSet<>();int used=0;
        for(Scored item:scored){String text=item.item().text().trim();String key=text.toLowerCase(Locale.ROOT).replace('ё','е').replaceAll("\\s+"," ");
            if(!seen.add(key)||text.length()>maxChars-used)continue;
            result.add(item.item());used+=text.length();if(result.size()>=limit)break;
        }
        return result;
    }
    private MemoryRetriever(){}
}
