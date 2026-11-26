package ru.wildlik.wileyai.mobile;

import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.Signature;
import java.security.interfaces.ECPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

final class UpdateSignature {
    private UpdateSignature() {}

    static byte[] verify(String publicKey, String encodedPayload, String encodedSignature) throws GeneralSecurityException {
        var decoder = Base64.getDecoder();
        var key = KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(decoder.decode(publicKey)));
        if (!(key instanceof ECPublicKey) || ((ECPublicKey) key).getParams().getCurve().getField().getFieldSize() != 256) {
            throw new GeneralSecurityException("Unexpected update key parameters");
        }
        byte[] payload = decoder.decode(encodedPayload);
        var verifier = Signature.getInstance("SHA256withECDSA");
        verifier.initVerify(key);
        verifier.update(payload);
        if (!verifier.verify(decoder.decode(encodedSignature))) throw new GeneralSecurityException("Invalid manifest signature");
        return payload;
    }
}
