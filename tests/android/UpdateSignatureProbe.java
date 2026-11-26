package ru.wildlik.wileyai.mobile;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Base64;

public final class UpdateSignatureProbe {
    public static void main(String[] args) throws Exception {
        byte[] bytes = UpdateSignature.verify(args[0], args[1], args[2]);
        if (!new String(bytes, StandardCharsets.UTF_8).contains("Проверка")) throw new AssertionError();
        String wrong = Base64.getEncoder().encodeToString("other payload".getBytes(StandardCharsets.UTF_8));
        try {
            UpdateSignature.verify(args[0], wrong, args[2]);
            throw new AssertionError("Changed payload accepted");
        } catch (GeneralSecurityException expected) {
            System.out.println("signature accepted; changed payload rejected");
        }
    }
}
