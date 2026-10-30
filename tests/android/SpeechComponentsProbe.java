import ru.wildlik.wileyai.mobile.VerifiedModelInstaller;
import ru.wildlik.wileyai.mobile.SpokenNames;
import ru.wildlik.wileyai.mobile.AppRegistry;
import ru.wildlik.wileyai.mobile.VoiceLabels;
import ru.wildlik.wileyai.mobile.WakePhrase;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.*;

public final class SpeechComponentsProbe {
    private static final VerifiedModelInstaller.Progress PROGRESS = (phase, done, total) -> {};
    private static void check(boolean condition) { if (!condition) throw new AssertionError(); }
    private static Path zip(Path root, String filename, String entry, String payload) throws Exception {
        Path file = root.resolve(filename);
        try (ZipOutputStream out = new ZipOutputStream(Files.newOutputStream(file))) {
            out.putNextEntry(new ZipEntry(entry)); out.write(payload.getBytes(StandardCharsets.UTF_8)); out.closeEntry();
        }
        return file;
    }
    private static VerifiedModelInstaller.Spec spec(Path file, long expanded) throws Exception {
        byte[] bytes = Files.readAllBytes(file);
        return new VerifiedModelInstaller.Spec("test-ru", bytes.length,
            VerifiedModelInstaller.hex(MessageDigest.getInstance("SHA-256").digest(bytes)),
            VerifiedModelInstaller.hex(MessageDigest.getInstance("MD5").digest(bytes)), expanded);
    }
    public static void main(String[] args) throws Exception {
        String scenario = args[0]; Path root = Paths.get(args[1]).toAbsolutePath(); Files.createDirectories(root);
        if (scenario.equals("wake-phrase")) {
            check(WakePhrase.matches(WakePhrase.DEFAULT, "Окей, Вайли!", .75));
            check(WakePhrase.matches(WakePhrase.DEFAULT, "окей уайли", 1)); check(WakePhrase.matches(WakePhrase.DEFAULT, "окей вай ли", 1));
            check(WakePhrase.matches("привет помощник", "Привет, помощник!", .75));
            check(WakePhrase.matches("слушай помощник", "слушай   помощник", 1));
            for (String text : new String[]{"окей", "вайли", "окей вай", "не окей вайли", "он сказал окей вайли", "окей вайли открой музыку", "окей вали", "", "слушай помощник"}) check(!WakePhrase.matches(WakePhrase.DEFAULT, text, 1));
            for (double confidence : new double[]{.749, 0, -1, Double.NaN, Double.POSITIVE_INFINITY, 1.01}) check(!WakePhrase.matches(WakePhrase.DEFAULT, WakePhrase.DEFAULT, confidence));
            check(!WakePhrase.matches("уайли", "уайли", 1)); check(!WakePhrase.matches(WakePhrase.DEFAULT, null, 1));
            System.out.println("passed: " + scenario); return;
        }
        if (scenario.equals("voice-labels")) {
            check(VoiceLabels.title("ru-ru-x-ruf-local", 2).equals("Русский голос 2"));
            check(VoiceLabels.title("Ирина", 1).equals("Ирина"));
            check(VoiceLabels.quality(0).contains("не указана"));
            check(VoiceLabels.quality(400).startsWith("Высокое"));
            check(VoiceLabels.quality(300).startsWith("Обычное"));
            System.out.println("passed: " + scenario); return;
        }
        if (scenario.startsWith("catalog-")) {
            AppRegistry.App personal = new AppRegistry.App("org.telegram/Main", "Telegram", "org.telegram", "Main", java.util.Arrays.asList("личный чат"));
            AppRegistry.App clone = new AppRegistry.App("org.clone/Main", "Telegram", "org.clone", "Main", java.util.Arrays.asList("рабочий чат"));
            AppRegistry.App music = new AppRegistry.App("ru.music/Main", "Яндекс Музыка", "ru.music", "Main", java.util.Arrays.asList("любимая музыка"));
            java.util.List<AppRegistry.App> apps = java.util.Arrays.asList(personal, clone, music);
            switch (scenario) {
                case "catalog-exact": check(AppRegistry.resolve(apps, "org.telegram").equals(java.util.Arrays.asList(personal))); break;
                case "catalog-ambiguous": check(AppRegistry.resolve(apps, "Телеграм").size() == 2); break;
                case "catalog-aliases": check(AppRegistry.resolve(apps, "рабочий чат").equals(java.util.Arrays.asList(clone))); break;
                case "catalog-rejects-fuzzy": check(AppRegistry.resolve(apps, "Telegr").isEmpty()); check(AppRegistry.resolve(apps, "").isEmpty()); break;
                case "catalog-search": check(AppRegistry.search(apps, "теле").size() == 2); check(AppRegistry.search(apps, "муз").equals(java.util.Arrays.asList(music))); break;
                case "catalog-removed": check(AppRegistry.resolve(java.util.Arrays.asList(clone, music), "личный чат").isEmpty()); break;
                case "catalog-nfkc": check(AppRegistry.resolve(apps, "Ｔｅｌｅｇｒａｍ").size() == 2); break;
                case "catalog-alias-validation":
                    check(AppRegistry.aliases("личный чат\nличный чат\nМузыка").size() == 2);
                    boolean rejected = false; try { AppRegistry.aliases("https://example.com"); } catch (IllegalArgumentException expected) { rejected = true; } check(rejected); break;
                default: throw new AssertionError(scenario);
            }
            System.out.println("passed: " + scenario); return;
        }
        if (scenario.equals("spoken-aliases")) {
            check(SpokenNames.app("Телеграм!").equals("telegram")); check(SpokenNames.app("Яндекс Музыку").equals("яндекс музыка"));
            check(SpokenNames.app("Telegram X").equals("telegram x")); check(SpokenNames.percent("девяносто девять") == 99);
            check(SpokenNames.percent("сто один") == -1); check(SpokenNames.percent("пятьдесят и открой") == -1);
            for(String name:new String[]{"дипсик","дип сик","тип сик","типсик","DeepSeek"})check(SpokenNames.app(name).equals("deepseek"));
            for(String[] pair:new String[][]{{"Квен","qwen"},{"чат джипити","chatgpt"},{"тик ток","tiktok"},{"термукс","termux"},{"рустор","rustore"}})check(SpokenNames.app(pair[0]).equals(pair[1]));
            java.util.List<AppRegistry.App> apps=java.util.Arrays.asList(new AppRegistry.App("d","DeepSeek","com.deepseek.chat","Main",java.util.Collections.emptyList()),new AppRegistry.App("t","Example","example.app","Main",java.util.Collections.emptyList()));
            check(AppRegistry.resolve(apps,"тип сик").get(0).id().equals("d"));check(AppRegistry.resolve(apps,"эксампле").get(0).id().equals("t"));
            check(AppRegistry.resolve(apps,"DeepSeak").isEmpty());check(AppRegistry.suggest(apps,"DeepSeak").get(0).id().equals("d"));
            check(AppRegistry.suggest(apps,"go").isEmpty());
            System.out.println("passed: " + scenario); return;
        }
        Path base = root.resolve("models"); Files.createDirectories(base);
        Path first = zip(root, "first.zip", "test-ru/am/final.mdl", "original-model");
        Path old = VerifiedModelInstaller.install(base, first, spec(first, 1024), new AtomicBoolean(), PROGRESS, directory -> check(Files.exists(directory.resolve("am/final.mdl"))));
        check(VerifiedModelInstaller.active(base).equals(old));
        if (scenario.equals("reopen")) { check(Files.readString(old.resolve("am/final.mdl")).equals("original-model")); System.out.println("passed: " + scenario); return; }
        if (scenario.equals("corrupt-pointer")) {
            Files.writeString(base.resolve("active"), "../outside"); boolean failed = false;
            try { VerifiedModelInstaller.active(base); } catch (IOException expected) { failed = true; }
            check(failed && Files.exists(old.resolve("am/final.mdl"))); System.out.println("passed: " + scenario); return;
        }
        String entry = scenario.equals("traversal") ? "test-ru/../escape.txt" : scenario.equals("absolute") ? "/test-ru/am/final.mdl" : scenario.equals("wrong-root") ? "other/am/final.mdl" : "test-ru/am/final.mdl";
        Path candidate = zip(root, "candidate.zip", entry, scenario.equals("expansion-limit") ? "a".repeat(10000) : "replacement-model");
        VerifiedModelInstaller.Spec valid = spec(candidate, scenario.equals("expansion-limit") ? 32 : 20000);
        VerifiedModelInstaller.Spec selected = valid;
        if (scenario.equals("bad-sha")) selected = new VerifiedModelInstaller.Spec(valid.id(), valid.bytes(), "0".repeat(64), valid.md5(), valid.maxExpanded());
        if (scenario.equals("bad-md5")) selected = new VerifiedModelInstaller.Spec(valid.id(), valid.bytes(), valid.sha256(), "0".repeat(32), valid.maxExpanded());
        if (scenario.equals("partial-download")) selected = new VerifiedModelInstaller.Spec(valid.id(), valid.bytes() + 10, valid.sha256(), valid.md5(), valid.maxExpanded());
        AtomicBoolean cancel = new AtomicBoolean(scenario.equals("cancelled"));
        boolean failed = false;
        try {
            Path replacement = VerifiedModelInstaller.install(base, candidate, selected, cancel, PROGRESS, directory -> {
                if (scenario.equals("engine-failure")) throw new IOException("native validation failed");
                if (scenario.equals("cancel-after-validation")) cancel.set(true);
            });
            check(scenario.equals("replace")); check(!replacement.equals(old)); check(VerifiedModelInstaller.active(base).equals(replacement)); check(Files.exists(old));
        } catch (IOException expected) { failed = true; }
        if (!scenario.equals("replace")) { check(failed); check(VerifiedModelInstaller.active(base).equals(old)); check(Files.readString(old.resolve("am/final.mdl")).equals("original-model")); }
        check(!Files.exists(base.resolve("escape.txt")));
        try (DirectoryStream<Path> dirs = Files.newDirectoryStream(base, "staging-*")) { check(!dirs.iterator().hasNext()); }
        System.out.println("passed: " + scenario);
    }
}
