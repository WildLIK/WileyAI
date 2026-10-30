import ru.wildlik.wileyai.mobile.ResumableDownload;
import com.sun.net.httpserver.*;
import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

/** Exercises the production transport against a real, bounded loopback HTTP server. */
public final class DownloadProbe {
    private static final byte[] DATA = new byte[320000];
    static { new Random(143).nextBytes(DATA); }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void range(HttpExchange request, int cap, AtomicInteger starts) throws IOException {
        String header = request.getRequestHeaders().getFirst("Range");
        check(header != null && header.matches("bytes=[0-9]+-[0-9]+"));
        String[] pieces = header.substring(6).split("-"); int start = Integer.parseInt(pieces[0]);
        starts.set(start); int end = Math.min(DATA.length - 1, Math.min(Integer.parseInt(pieces[1]), start + cap - 1));
        request.getResponseHeaders().set("Content-Range", "bytes " + start + "-" + end + "/" + DATA.length);
        request.sendResponseHeaders(206, end - start + 1);
        try (OutputStream out = request.getResponseBody()) { out.write(DATA, start, end - start + 1); }
    }
    public static void main(String[] args) throws Exception {
        String scenario = args[0]; Path file = Paths.get(args[1]).resolve("archive.part"); Files.createDirectories(file.getParent());
        AtomicInteger requests = new AtomicInteger(), starts = new AtomicInteger(-1), fallbacks = new AtomicInteger(), retries = new AtomicInteger();
        AtomicBoolean cancel = new AtomicBoolean();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/good", request -> { requests.incrementAndGet(); range(request, scenario.equals("short-ranges") ? 40000 : DATA.length, starts); });
        server.createContext("/mirror", request -> { fallbacks.incrementAndGet(); range(request, DATA.length, starts); });
        server.createContext("/redirect", request -> { requests.incrementAndGet(); request.getResponseHeaders().set("Location", "/good"); request.sendResponseHeaders(307, -1); request.close(); });
        server.createContext("/full", request -> { requests.incrementAndGet(); request.sendResponseHeaders(200, DATA.length); try (OutputStream out = request.getResponseBody()) { out.write(DATA); } });
        server.createContext("/bad", request -> {
            requests.incrementAndGet();
            if (scenario.equals("truncated-fallback")) {
                request.getResponseHeaders().set("Connection", "close");
                request.getResponseHeaders().set("Content-Range", "bytes 0-" + (DATA.length - 1) + "/" + DATA.length);
                request.sendResponseHeaders(206, DATA.length);
                try (OutputStream out = request.getResponseBody()) { out.write(DATA, 0, 32225); } catch (IOException expected) { request.close(); }
            } else if (scenario.equals("invalid-range")) {
                request.getResponseHeaders().set("Content-Range", "bytes 1-10/" + DATA.length); request.sendResponseHeaders(206, 10);
                try (OutputStream out = request.getResponseBody()) { out.write(DATA, 0, 10); }
            } else { request.sendResponseHeaders(503, -1); request.close(); }
        });
        server.start();
        try {
            String endpoint = "http://127.0.0.1:" + server.getAddress().getPort();
            String first = switch (scenario) { case "redirect" -> "/redirect"; case "range-ignored" -> "/full"; case "truncated-fallback", "invalid-range", "bounded-retries" -> "/bad"; default -> "/good"; };
            if (Set.of("resume", "range-ignored", "invalid-range", "cancelled").contains(scenario)) Files.write(file, Arrays.copyOf(DATA, 32225));
            List<ResumableDownload.Source> sources = new ArrayList<>(); sources.add(new ResumableDownload.Source("primary", new URL(endpoint + first)));
            if (scenario.equals("truncated-fallback") || scenario.equals("cancelled")) sources.add(new ResumableDownload.Source("mirror", new URL(endpoint + "/mirror")));
            boolean failed = false;
            try {
                ResumableDownload.download(sources, file, DATA.length, cancel, url -> (HttpURLConnection)url.openConnection(), new ResumableDownload.Observer() {
                    public void progress(String source, long done, long total) { check(total == DATA.length && done <= total); }
                    public void retry(String source, String reason) { retries.incrementAndGet(); }
                    public void connection(HttpURLConnection connection) { if (connection != null && scenario.equals("cancelled")) cancel.set(true); }
                });
            } catch (IOException expected) { failed = true; }
            if (Set.of("invalid-range", "cancelled", "bounded-retries").contains(scenario)) {
                check(failed); check(fallbacks.get() == 0);
                if (scenario.equals("bounded-retries")) { check(requests.get() == 3 && retries.get() == 2); check(!Files.exists(file)); }
                else { check(Arrays.equals(Files.readAllBytes(file), Arrays.copyOf(DATA, 32225))); check(requests.get() == (scenario.equals("cancelled") ? 0 : 3)); }
            } else {
                check(!failed); check(Arrays.equals(Files.readAllBytes(file), DATA));
                switch (scenario) {
                    case "resume": check(starts.get() == 32225); break;
                    case "short-ranges": check(requests.get() == 8); break;
                    case "truncated-fallback": check(fallbacks.get() == 1 && starts.get() == 32225 && retries.get() == 1); break;
                    case "redirect": check(requests.get() == 2); break;
                    case "range-ignored": check(requests.get() == 1); break;
                    default: throw new AssertionError(scenario);
                }
            }
            System.out.println("passed: " + scenario);
        } finally { server.stop(0); }
    }
}
