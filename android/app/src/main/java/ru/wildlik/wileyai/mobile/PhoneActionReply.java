package ru.wildlik.wileyai.mobile;

import java.util.function.Consumer;

/** Separate visible details from verified, concise speech. */
interface PhoneActionReply extends Consumer<String> {
    void result(String display, String spoken);
    @Override default void accept(String display) { result(display, display); }
}
