package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.Color;

/** Color tokens copied from src/themes.css, not an independent mobile palette. */
final class WileyTheme {
    static final String[] IDS = {"system", "aurora", "ice", "ember", "nebula"};
    static final String[] NAMES = {"Как в системе", "Аврора", "Ледяной свет", "Красный контур", "Туманность"};
    final int base, low, mid, high, text, secondary, muted, accent, accentText, accentInk, border;
    final int dialogStyle;
    private WileyTheme(String... colors) {
        base = color(colors[0]); low = color(colors[1]); mid = color(colors[2]); high = color(colors[3]);
        text = color(colors[4]); secondary = color(colors[5]); muted = color(colors[6]); accent = color(colors[7]);
        accentText = color(colors[8]); accentInk = color(colors[9]); border = color(colors[10]);
        dialogStyle = switch (colors[0]) {
            case "#e6f1fa" -> R.style.WileyDialog_Ice;
            case "#0b0b10" -> R.style.WileyDialog_Ember;
            case "#07060d" -> R.style.WileyDialog_Nebula;
            default -> R.style.WileyDialog_Aurora;
        };
    }
    private static int color(String value) { return Color.parseColor(value); }
    static WileyTheme resolve(Context context, String selected) {
        if ("system".equals(selected)) selected = (context.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES ? "aurora" : "ice";
        return switch (selected) {
            case "ice" -> new WileyTheme("#e6f1fa", "#f4f9fe", "#e5f0fa", "#d5e6f4", "#142f49", "#34536e", "#4d6b83", "#0967ad", "#07588f", "#ffffff", "#b3cbdf");
            case "ember" -> new WileyTheme("#0b0b10", "#141317", "#201b20", "#30262c", "#fff1f2", "#d6bdc5", "#b59ca8", "#ff4e62", "#ff9caa", "#240c14", "#4c303b");
            case "nebula" -> new WileyTheme("#07060d", "#111020", "#1b1730", "#2a2440", "#f5f0ff", "#d6cde8", "#afa3c6", "#c6adff", "#ddccff", "#211331", "#413653");
            default -> new WileyTheme("#080f1c", "#101b2c", "#15243a", "#20354b", "#edf7ff", "#b7cadd", "#91a9be", "#77e3ee", "#99edf4", "#06252f", "#2c435c");
        };
    }
}
