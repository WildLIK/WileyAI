package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.os.Build;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

/** Writes only neutral data into a freshly provisioned emulator profile. */
final class ReleaseUpgradeProbe {
    private static final String CHAT = "Изолированная проверка выпуска";
    private static final String MEMORY = "Тестовый цвет бирюзовый";
    private static final byte[] MODEL_MARKER = {12, 44, 86};

    static String run(Context context, boolean seed) throws Exception {
        require("ranchu".equals(Build.HARDWARE) || "goldfish".equals(Build.HARDWARE), "Disposable emulator required");
        var marker = context.getFilesDir().toPath().resolve("llm-models/release-upgrade-fixture.bin");
        var settings = context.getSharedPreferences("wiley-mobile", Context.MODE_PRIVATE);
        var probe = context.getSharedPreferences("release-upgrade-fixture", Context.MODE_PRIVATE);
        var personalization = new PersonalPreferences(context);
        var chat = new LocalChatRepository(context);
        try {
            long code = context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode();
            if (seed) {
                require(chat.chats().isEmpty() && personalization.memories().isEmpty() && !Files.exists(marker)
                        && !probe.contains("before"), "Probe requires an unused profile");
                var id = chat.submit("", CHAT);
                chat.append(id, "assistant", "Нейтральный ответ");
                chat.draft(id, "Черновик");
                personalization.profile("Проба", "", "Нейтральные данные");
                personalization.saveMemory(null, MEMORY);
                require(settings.edit().putString("theme", "ice").putString("phone_chat", id).commit(), "settings");
                Files.createDirectories(marker.getParent());
                Files.write(marker, MODEL_MARKER);
                require(probe.edit().putLong("before", code).putString("chat_id", id).commit(), "seed");
                return "SEEDED " + code;
            }
            var id = probe.getString("chat_id", "");
            require(probe.getLong("before", 0) + 1 == code && !id.isEmpty(), "Successive versionCode required");
            require("ice".equals(settings.getString("theme", "")) && id.equals(settings.getString("phone_chat", "")), "settings");
            require("Проба".equals(personalization.name()) && personalization.memories().stream()
                    .anyMatch(memory -> MEMORY.equals(memory.text())), "memory and profile");
            var messages = chat.messages(id, 10);
            require(messages.size() == 2 && CHAT.equals(messages.get(0).content())
                    && "Черновик".equals(chat.chat(id).draft()), "conversation and draft");
            require(java.util.Arrays.equals(Files.readAllBytes(marker), MODEL_MARKER), "model file");
            return "PRESERVED settings/profile/memory/chat/draft/model-marker " + code;
        } finally {
            chat.close();
        }
    }

    private static void require(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
    }
}
