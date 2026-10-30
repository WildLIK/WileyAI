package ru.wildlik.wileyai.mobile;

import java.text.Normalizer;
import java.util.*;

/** Exact matching against an observed launcher catalog. No fuzzy auto-launches. */
public final class AppRegistry {
    public record App(String id, String label, String packageName, String activity, List<String> aliases) {}
    private AppRegistry() {}
    public static String key(String text) {
        return SpokenNames.app(Normalizer.normalize(text, Normalizer.Form.NFKC)).replaceAll("\\s+", " ").trim();
    }
    public static List<App> resolve(List<App> apps, String name) {
        String expected = key(name); List<App> matches = new ArrayList<>(); Set<String> ids = new HashSet<>();
        if (expected.isEmpty()) return matches;
        for (App app : apps) {
            boolean match = same(app.label(), expected) || app.packageName().equalsIgnoreCase(name.trim());
            for (String alias : app.aliases()) if (same(alias, expected)) match = true;
            for (String alias : SpokenNames.alternatives(app.label())) if (same(alias, expected)) match = true;
            if (match && ids.add(app.id())) matches.add(app);
        }
        return matches;
    }
    private static boolean same(String name, String expected) { return SpokenNames.compact(key(name)).equals(SpokenNames.compact(expected)); }
    /** Approximate matches are suggestions only; callers must always ask before opening. */
    public static List<App> suggest(List<App> apps, String name) {
        String wanted = SpokenNames.compact(key(name)); if (wanted.length() < 4) return Collections.emptyList();
        List<App> result = new ArrayList<>(); int best = Math.min(3, wanted.length() / 4);
        for (App app : apps) {
            List<String> labels = new ArrayList<>(app.aliases()); labels.add(app.label()); labels.addAll(SpokenNames.alternatives(app.label()));
            int score = 100;
            for (String label : labels) score = Math.min(score, distance(wanted, SpokenNames.compact(key(label))));
            if (score > best) continue;
            if (score < best) { result.clear(); best = score; }
            if (result.size() < 5) result.add(app);
        }
        return result;
    }
    private static int distance(String left, String right) {
        if (Math.abs(left.length()-right.length()) > 3 || right.length()>100) return 100;
        int[] old = new int[right.length()+1]; for(int j=0;j<old.length;j++)old[j]=j;
        for(int i=1;i<=left.length();i++){int[] row=new int[right.length()+1];row[0]=i;for(int j=1;j<row.length;j++)row[j]=Math.min(Math.min(row[j-1]+1,old[j]+1),old[j-1]+(left.charAt(i-1)==right.charAt(j-1)?0:1));old=row;}return old[right.length()];
    }
    public static List<App> search(List<App> apps, String query) {
        String wanted = key(query); List<App> found = new ArrayList<>();
        for (App app : apps) {
            boolean match = key(app.label()).contains(wanted) || app.packageName().toLowerCase(Locale.ROOT).contains(wanted);
            for (String alias : app.aliases()) if (key(alias).contains(wanted)) match = true;
            for (String alias : SpokenNames.alternatives(app.label())) if (alias.contains(query.toLowerCase(Locale.ROOT).replace('ё', 'е').trim())) match = true;
            if (match) found.add(app);
        }
        return found;
    }
    public static List<String> aliases(String text) {
        LinkedHashSet<String> aliases = new LinkedHashSet<>();
        for (String line : text.split("[\\r\\n]+")) {
            String alias = line.trim(); if (alias.isEmpty()) continue;
            if (!alias.matches("[\\p{L}\\p{N} .+_-]{1,60}")) throw new IllegalArgumentException("Название: до 60 букв, цифр, пробелов, точек, +, _ или дефисов");
            aliases.add(alias);
            if (aliases.size() > 12) throw new IllegalArgumentException("Для одного приложения можно задать до 12 названий");
        }
        return new ArrayList<>(aliases);
    }
}
