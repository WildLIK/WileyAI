package ru.wildlik.wileyai.mobile;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.spec.*;
import java.util.*;

/** Offline OIDC identity validation against a trusted HTTPS-discovered JWKS, not an unverified JWT. */
public final class JwtIdentity {
    private static Map<?,?> object(byte[] value){Object decoded=StrictJson.parse(new String(value,StandardCharsets.UTF_8));if(!(decoded instanceof Map<?,?> map))throw new IllegalArgumentException("Invalid JWT object");return map;}
    private static byte[] decode(String text){if(text.length()>32000)throw new IllegalArgumentException();return Base64.getUrlDecoder().decode(text);}
    private static long numeric(Object value){if(!(value instanceof Number number)||!Double.isFinite(number.doubleValue()))throw new IllegalArgumentException();return number.longValue();}
    public static Map<?,?> validate(String token,String client,String nonce,String subject,Map<?,?> jwks,long now)throws Exception{
        if(token==null||token.length()>32000)throw new IllegalArgumentException();String[] parts=token.split("\\.",-1);if(parts.length!=3)throw new IllegalArgumentException();Map<?,?> header=object(decode(parts[0])),claims=object(decode(parts[1]));String alg=String.valueOf(header.get("alg")),kid=String.valueOf(header.get("kid"));if(!List.of("RS256","ES256").contains(alg)||kid.equals("null"))throw new IllegalArgumentException();
        Object entries=jwks.get("keys");if(!(entries instanceof List<?> keys)||keys.size()>100)throw new IllegalArgumentException();Map<?,?> key=null;for(Object entry:keys)if(entry instanceof Map<?,?> candidate&&kid.equals(candidate.get("kid"))){if(key!=null)throw new IllegalArgumentException();key=candidate;}if(key==null||key.containsKey("alg")&&!alg.equals(key.get("alg"))||key.containsKey("use")&&!"sig".equals(key.get("use")))throw new IllegalArgumentException();
        if(key.containsKey("key_ops")&&(!(key.get("key_ops") instanceof List<?> operations)||!operations.contains("verify")))throw new IllegalArgumentException();
        PublicKey publicKey;byte[] signature=decode(parts[2]);
        if(alg.equals("RS256")){if(!"RSA".equals(key.get("kty")))throw new IllegalArgumentException();BigInteger n=new BigInteger(1,decode((String)key.get("n"))),e=new BigInteger(1,decode((String)key.get("e")));if(n.bitLength()<2048||n.bitLength()>8192||e.bitLength()>32||!e.testBit(0)||e.compareTo(BigInteger.valueOf(3))<0)throw new IllegalArgumentException();publicKey=KeyFactory.getInstance("RSA").generatePublic(new RSAPublicKeySpec(n,e));}
        else{if(!"EC".equals(key.get("kty"))||!"P-256".equals(key.get("crv")))throw new IllegalArgumentException();AlgorithmParameters params=AlgorithmParameters.getInstance("EC");params.init(new ECGenParameterSpec("secp256r1"));byte[] x=decode((String)key.get("x")),y=decode((String)key.get("y"));if(x.length!=32||y.length!=32)throw new IllegalArgumentException();publicKey=KeyFactory.getInstance("EC").generatePublic(new ECPublicKeySpec(new ECPoint(new BigInteger(1,x),new BigInteger(1,y)),params.getParameterSpec(ECParameterSpec.class)));signature=der(signature);}
        Signature verifier=Signature.getInstance(alg.equals("RS256")?"SHA256withRSA":"SHA256withECDSA");verifier.initVerify(publicKey);verifier.update((parts[0]+"."+parts[1]).getBytes(StandardCharsets.US_ASCII));if(!verifier.verify(signature))throw new IllegalArgumentException();
        if(!"https://auth.openai.com".equals(claims.get("iss"))||numeric(claims.get("exp"))<now-30||numeric(claims.get("iat"))>now+60||numeric(claims.get("exp"))<=numeric(claims.get("iat")))throw new IllegalArgumentException();Object aud=claims.get("aud");boolean allowed=client.equals(aud)||aud instanceof List<?> list&&list.contains(client);if(!allowed||claims.containsKey("azp")&&!client.equals(claims.get("azp"))||aud instanceof List<?> list&&list.size()>1&&!client.equals(claims.get("azp")))throw new IllegalArgumentException();
        if(!(claims.get("sub") instanceof String sub)||sub.isEmpty()||subject!=null&&!subject.equals(sub))throw new IllegalArgumentException();if(nonce!=null&&(!(claims.get("nonce") instanceof String value)||!MessageDigest.isEqual(nonce.getBytes(StandardCharsets.UTF_8),value.getBytes(StandardCharsets.UTF_8))))throw new IllegalArgumentException();return claims;
    }
    private static byte[] der(byte[] signature){if(signature.length!=64)throw new IllegalArgumentException();byte[] r=new BigInteger(1,Arrays.copyOfRange(signature,0,32)).toByteArray(),s=new BigInteger(1,Arrays.copyOfRange(signature,32,64)).toByteArray();byte[] out=new byte[6+r.length+s.length];int at=0;out[at++]=0x30;out[at++]=(byte)(out.length-2);out[at++]=2;out[at++]=(byte)r.length;System.arraycopy(r,0,out,at,r.length);at+=r.length;out[at++]=2;out[at++]=(byte)s.length;System.arraycopy(s,0,out,at,s.length);return out;}
    private JwtIdentity(){}
}
