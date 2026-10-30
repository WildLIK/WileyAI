package ru.wildlik.wileyai.mobile;

import android.graphics.Typeface;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.RelativeSizeSpan;
import android.text.style.StyleSpan;
import android.text.style.TypefaceSpan;
import android.widget.TextView;

/** Deliberately small Markdown subset. No HTML, images, scripts or automatic URL requests. */
final class MessageRenderer {
    static void render(TextView view, String content) { view.setText(format(content)); }
    static CharSequence format(String content) {
        SpannableStringBuilder output = new SpannableStringBuilder();
        boolean code = false;
        for (String line : content.split("\n", -1)) {
            if (line.startsWith("```")) { code = !code; continue; }
            int start = output.length();
            boolean heading = !code && line.matches("^#{1,3} .*" );
            if (heading) line = line.replaceFirst("^#{1,3} ", "");
            if (code) { output.append(line); output.setSpan(new TypefaceSpan("monospace"), start, output.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE); }
            else {
                for (int i = 0; i < line.length();) {
                    String delimiter = line.startsWith("**", i) ? "**" : line.charAt(i) == '`' ? "`" : "";
                    int end = delimiter.isEmpty() ? -1 : line.indexOf(delimiter, i + delimiter.length());
                    if (end > i + delimiter.length()) {
                        int from = output.length(); output.append(line, i + delimiter.length(), end);
                        output.setSpan(delimiter.equals("`") ? new TypefaceSpan("monospace") : new StyleSpan(Typeface.BOLD), from, output.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                        i = end + delimiter.length();
                    } else { output.append(line.charAt(i)); i++; }
                }
            }
            if (heading) { output.setSpan(new StyleSpan(Typeface.BOLD), start, output.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE); output.setSpan(new RelativeSizeSpan(1.15f), start, output.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE); }
            output.append('\n');
        }
        if (output.length() > 0) output.delete(output.length() - 1, output.length());
        return output;
    }
}
