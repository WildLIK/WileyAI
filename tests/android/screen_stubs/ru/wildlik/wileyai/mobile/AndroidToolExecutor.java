package ru.wildlik.wileyai.mobile;
public class AndroidToolExecutor {interface Host {boolean active();boolean screenAuthorized();default boolean voiceOverlay(){return false;}}}
