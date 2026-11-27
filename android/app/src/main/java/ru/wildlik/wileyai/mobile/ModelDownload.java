package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Locale;

/** The supported HTTPS hosts and the Android network policy for public model files. */
final class ModelDownload {
    private static final String MIRROR = "https://github.com/WildLIK/WileyAI/releases/download/android-models-v1/";

    static ResumableDownload.Source mirror(String file) throws IOException {
        return source("GitHub Releases", MIRROR + file);
    }

    static ResumableDownload.Source source(String name, String url) throws IOException {
        return new ResumableDownload.Source(name, new URL(url));
    }

    static HttpURLConnection connect(Context context, boolean wifiOnly, URL url) throws IOException {
        String host = url.getHost().toLowerCase(Locale.ROOT);
        boolean trusted = host.equals("github.com") || host.equals("release-assets.githubusercontent.com")
                || host.equals("objects.githubusercontent.com") || host.equals("alphacephei.com")
                || host.equals("huggingface.co") || host.endsWith(".huggingface.co") || host.endsWith(".hf.co")
                || host.equals("modelscope.cn") || host.endsWith(".modelscope.cn");
        if (!trusted || !url.getProtocol().equals("https") || url.getUserInfo() != null || (url.getPort() != -1 && url.getPort() != 443)) {
            throw new IOException("Источник перенаправил загрузку на неподдерживаемый адрес");
        }
        if (!wifiOnly) return (HttpURLConnection) url.openConnection();
        ConnectivityManager manager = context.getSystemService(ConnectivityManager.class);
        Network network = manager.getActiveNetwork();
        NetworkCapabilities capabilities = network == null ? null : manager.getNetworkCapabilities(network);
        if (capabilities == null || !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) {
            throw new IOException("Для загрузки подключитесь к Wi-Fi или отключите режим «Только Wi-Fi».");
        }
        return (HttpURLConnection) network.openConnection(url);
    }

    private ModelDownload() {}
}
