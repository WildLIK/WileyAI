package ru.wildlik.wileyai.mobile;

import android.os.Build;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.*;
import java.util.zip.*;
import org.json.*;

/** Private files owned exclusively by the acoustic-diagnostics I/O executor. */
final class AcousticStore {
    static final String ROOT = "WileyAI_Wake_Diagnostics/";
    private static final int MAX_EXPORT_EVENTS = 2400;
    private static final String[] SERIES = {"audio_route", "performance", "voice_tests"};
    final Path root;

    AcousticStore(Path directory) { root = directory; }

    static JSONObject fields(Object... pairs) {
        JSONObject result = new JSONObject();
        try {
            for (int i = 0; i < pairs.length; i += 2) result.put((String)pairs[i], pairs[i + 1] == null ? JSONObject.NULL : pairs[i + 1]);
        } catch (JSONException invalid) { throw new IllegalArgumentException(invalid); }
        return result;
    }
    static JSONObject stamp(long utc, long elapsed, Object... pairs) {
        JSONObject result = fields(pairs);
        set(result, "utc", Instant.ofEpochMilli(utc).toString());
        set(result, "elapsed_ms", elapsed);
        return result;
    }
    static void set(JSONObject object, String key, Object value) {
        try { object.put(key, value == null ? JSONObject.NULL : value); }
        catch (JSONException invalid) { throw new IllegalArgumentException(invalid); }
    }

    Path session(String id) {
        if (!id.matches("[a-f0-9-]{36}")) throw new IllegalArgumentException("invalid session");
        return root.resolve(id);
    }
    static String id(JSONObject event) {
        String id = event.optString("id");
        if (!id.matches("[a-z0-9_-]{1,45}")) throw new IllegalArgumentException("invalid event");
        return id;
    }
    void write(Path file, JSONObject value) throws IOException {
        Files.createDirectories(file.getParent());
        Path temp = file.resolveSibling(file.getFileName() + ".tmp");
        Files.write(temp, value.toString().getBytes(StandardCharsets.UTF_8));
        try { Files.move(temp, file, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING); }
        catch (AtomicMoveNotSupportedException error) { Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING); }
    }
    void event(Path session, JSONObject value) throws IOException { write(session.resolve("events").resolve(id(value) + ".json"), value); }
    void line(Path session, String series, JSONObject value) throws IOException {
        if (!Arrays.asList(SERIES).contains(series)) throw new IllegalArgumentException("invalid stream");
        Path log = session.resolve(series + ".jsonl");
        if (Files.exists(log) && Files.size(log) >= 768 * 1024) return;
        Files.createDirectories(session);
        Files.write(log, (value + "\n").getBytes(StandardCharsets.UTF_8), StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }

    static List<Path> children(Path dir) throws IOException {
        if (!Files.isDirectory(dir)) return List.of();
        try (var paths = Files.list(dir)) { return paths.sorted().collect(java.util.stream.Collectors.toList()); }
    }
    static JSONObject read(Path file) throws IOException {
        try { return new JSONObject(new String(Files.readAllBytes(file), StandardCharsets.UTF_8)); }
        catch (JSONException invalid) { throw new IOException("invalid metadata", invalid); }
    }
    static void erase(Path owned) throws IOException {
        if (!Files.exists(owned)) return;
        try (var tree = Files.walk(owned)) {
            for (Path path : tree.sorted(Comparator.reverseOrder()).collect(java.util.stream.Collectors.toList())) Files.deleteIfExists(path);
        }
    }
    void remove(JSONObject event) throws IOException {
        Path session = session(event.optString("session_id"));
        String id = id(event);
        if (event.optString("kind").equals("continuous")) {
            for (Path record : children(session.resolve("events"))) {
                JSONObject dependent = read(record);
                if (id.equals(dependent.optString("audio_ref"))) Files.deleteIfExists(record);
            }
        }
        for (String suffix : new String[]{".flac", ".wav", ".pcm.part", ".flac.part", ".wav.part"})
            Files.deleteIfExists(session.resolve("audio").resolve(id + suffix));
        Files.deleteIfExists(session.resolve("events").resolve(id + ".json"));
        Files.deleteIfExists(session.resolve("windows").resolve(id + ".json"));
    }
    List<JSONObject> events() throws IOException {
        List<JSONObject> result = new ArrayList<>();
        for (Path dir : children(root)) {
            for (Path file : children(dir.resolve("events"))) {
                if (file.getFileName().toString().endsWith(".json")) result.add(read(file));
            }
        }
        result.sort(Comparator.comparing((JSONObject row) -> row.optString("utc")).reversed());
        return result;
    }
    long used() throws IOException {
        if (!Files.exists(root)) return 0;
        long total = 0;
        try (var files = Files.walk(root)) {
            for (Path file : files.filter(Files::isRegularFile).collect(java.util.stream.Collectors.toList())) total += Files.size(file);
        }
        return total;
    }
    boolean reserve(long bytes, long limit, boolean prune, Path active) throws IOException {
        long current = used();
        if (prune && current + bytes > limit) {
            List<Path> sessions = new ArrayList<>(children(root));
            sessions.sort(Comparator.comparingLong(dir -> dir.toFile().lastModified()));
            for (Path old : sessions) {
                if (old.equals(active) || !Files.isDirectory(old)) continue;
                erase(old);
                current = used();
                if (current + bytes <= limit) break;
            }
        }
        return current + bytes <= limit && root.toFile().getUsableSpace() >= bytes + 8 * 1024 * 1024L;
    }
    static String hash(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(file)) {
            byte[] buf = new byte[8192];
            for (int n; (n = in.read(buf)) != -1;) digest.update(buf, 0, n);
        }
        StringBuilder value = new StringBuilder();
        for (byte b : digest.digest()) value.append(String.format(Locale.ROOT, "%02x", b & 255));
        return value.toString();
    }
    void publishAudio(Path dir, Path pcm, JSONObject event) throws Exception {
        try {
            for (String extension : new String[]{".flac", ".wav"}) {
                Path file = dir.resolve("audio").resolve(id(event) + extension);
                Path temp = file.resolveSibling(file.getFileName() + ".part");
                try {
                    AcousticAudio.encode(pcm, temp, extension.equals(".flac"));
                    String digest = hash(temp);
                    Files.move(temp, file, StandardCopyOption.REPLACE_EXISTING);
                    set(event, "audio", "audio/" + file.getFileName());
                    set(event, "sha256", digest);
                    set(event, "format", extension.substring(1));
                    return;
                } catch (IOException failure) {
                    set(event, "audio_error", extension.equals(".flac") ? "flac_encoder_io" : "wav_io");
                } finally { Files.deleteIfExists(temp); }
            }
        } finally { Files.deleteIfExists(pcm); }
    }
    Path audio(JSONObject event) throws IOException {
        Path dir = session(event.optString("session_id"));
        if (event.has("audio_ref")) event = read(dir.resolve("events").resolve(id(fields("id", event.optString("audio_ref"))) + ".json"));
        String name = event.optString("audio");
        if (!name.matches("audio/[a-z0-9_-]{1,45}\\.(flac|wav)")) throw new IOException("Аудиофайл отсутствует");
        Path path = dir.resolve(name);
        if (!Files.isRegularFile(path)) throw new IOException("Аудиофайл отсутствует");
        return path;
    }

    void export(OutputStream output, List<JSONObject> events, List<String> voiceJournal, long limit, boolean prune) throws Exception {
        if (events.size() > MAX_EXPORT_EVENTS) throw new IOException("Слишком много событий");
        try (ZipOutputStream zip = new ZipOutputStream(new BufferedOutputStream(output))) {
            put(zip, "manifest.json", fields("schema", 1, "app_version", BuildConfig.VERSION_NAME,
                    "version_code", BuildConfig.VERSION_CODE, "created_utc", Instant.now().toString(),
                    "sample_rate", AcousticCapture.RATE, "channels", 1, "bits", 16,
                    "input", "AudioRecord_application_pcm_android_processing_possible", "processed", "not_separately_available",
                    "vosk", "0.3.75", "gigaam", "v3", "audio_path_format", "audio/<session_id>_<event_id>_<raw_or_continuous>.<format>",
                    "timeline", "elapsedRealtime device-boot clock; utc wall clock; zero-based sample positions per capture_id",
                    "replay", "recognition.jsonl").toString());
            put(zip, "device.json", fields("manufacturer", Build.MANUFACTURER, "model", Build.MODEL, "sdk", Build.VERSION.SDK_INT,
                    "abi", Build.SUPPORTED_ABIS.length == 0 ? "unknown" : Build.SUPPORTED_ABIS[0]).toString());
            JSONArray settings = new JSONArray();
            for (Path dir : children(root)) {
                Path config = dir.resolve("session.json");
                if (Files.isRegularFile(config)) settings.put(read(config));
            }
            put(zip, "settings.json", fields("limit_bytes", limit, "prune_old_sessions", prune, "sessions", settings).toString());
            StringBuilder lines = new StringBuilder(), recognition = new StringBuilder();
            Set<String> liveIds = new HashSet<>();
            Set<String> added = new HashSet<>();
            int missing = 0;
            for (JSONObject event : events) {
                JSONObject row = new JSONObject(event.toString());
                String session = row.optString("session_id"), id = id(row);
                liveIds.add(id);
                if (row.has("audio")) {
                    Path path = audio(row);
                    String suffix = row.optString("kind").equals("continuous") ? "_continuous." : "_raw.";
                    String entry = "audio/" + session + "_" + id + suffix + row.optString("format");
                    if (added.add(entry)) {
                        zip.putNextEntry(new ZipEntry(ROOT + entry));
                        Files.copy(path, zip);
                        zip.closeEntry();
                    }
                    set(row, "audio", entry);
                } else if (!row.has("audio_ref")) missing++;
                if (row.has("vosk_final") || row.has("gigaam") || row.has("vosk_replay")) {
                    JSONObject result = fields("id", id, "session_id", session, "utc", row.optString("utc"));
                    for (String key : new String[]{"vosk_final", "partial", "gigaam", "vosk_replay", "analysis_runs"}) {
                        if (row.has(key)) set(result, key, row.remove(key));
                    }
                    recognition.append(result).append('\n');
                }
                lines.append(row).append('\n');
            }
            put(zip, "events.jsonl", lines.toString());
            put(zip, "summary.json", fields("events", events.size(), "audio_files", added.size(), "no_direct_audio", missing).toString());
            put(zip, "recognition.jsonl", recognition.toString());
            for (String series : SERIES) {
                zip.putNextEntry(new ZipEntry(ROOT + series + ".jsonl"));
                for (Path dir : children(root)) {
                    Path file = dir.resolve(series + ".jsonl");
                    if (Files.isRegularFile(file)) Files.copy(file, zip);
                }
                if (series.equals("performance")) {
                    Set<String> turns = new HashSet<>();
                    for (String original : voiceJournal) {
                        String[] part = original.split("\\|");
                        if (part.length == 5 && part[2].equals("WAKE_TURN_LINK") && liveIds.contains(part[4])) turns.add(part[3]);
                    }
                    for (String original : voiceJournal) {
                        String[] part = original.split("\\|");
                        if (part.length != 5 || (!liveIds.contains(part[4]) && !turns.contains(part[4]))) continue;
                        JSONObject row = fields("utc", Instant.ofEpochMilli(Long.parseLong(part[0])).toString(), "event", part[2],
                                "value", part[3], "correlation_id", part[4], "source", "numeric_journal");
                        zip.write((row + "\n").getBytes(StandardCharsets.UTF_8));
                    }
                }
                zip.closeEntry();
            }
        }
    }
    private static void put(ZipOutputStream zip, String name, String data) throws IOException {
        zip.putNextEntry(new ZipEntry(ROOT + name));
        zip.write(data.getBytes(StandardCharsets.UTF_8));
        zip.closeEntry();
    }
}
