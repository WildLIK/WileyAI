package ru.wildlik.wileyai.mobile;

import android.content.Context;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import org.json.JSONArray;
import org.json.JSONObject;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Keeps the v1 pairing ciphertext and Keystore alias compatible with 0.2.0. */
final class SettingsRepository {
    private static final String KEY_ALIAS = "wileyai.mobile.connection.v1";
    final android.content.SharedPreferences preferences;
    SettingsRepository(Context context) { this(context,"wiley-mobile"); }
    SettingsRepository(Context context,String name) { preferences = context.getSharedPreferences(name, Context.MODE_PRIVATE); }
    String theme() { return preferences.getString("theme", "system"); }
    void theme(String value) { preferences.edit().putString("theme", value).apply(); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (store.containsAlias(KEY_ALIAS)) return (SecretKey) store.getKey(KEY_ALIAS, null);
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
        return generator.generateKey();
    }
    void saveProfile(JSONObject value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] encrypted = cipher.doFinal(value.toString().getBytes(StandardCharsets.UTF_8));
        byte[] iv = cipher.getIV(), combined = new byte[iv.length + encrypted.length];
        System.arraycopy(iv, 0, combined, 0, iv.length); System.arraycopy(encrypted, 0, combined, iv.length, encrypted.length);
        if (!preferences.edit().putString("connection", Base64.encodeToString(combined, Base64.NO_WRAP)).commit())
            throw new Exception("Не удалось сохранить подключение на телефоне");
    }
    JSONObject readProfile() throws Exception {
        String encoded = preferences.getString("connection", "");
        if (encoded.isEmpty()) return null;
        byte[] combined = Base64.decode(encoded, Base64.DEFAULT);
        if (combined.length < 29) throw new Exception();
        byte[] iv = new byte[12], encrypted = new byte[combined.length - 12];
        System.arraycopy(combined, 0, iv, 0, 12); System.arraycopy(combined, 12, encrypted, 0, encrypted.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
        JSONObject value = new JSONObject(new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8));
        validateProfile(value, true); return value;
    }
    void saveCloud(JSONObject value) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        byte[] encrypted=cipher.doFinal(value.toString().getBytes(StandardCharsets.UTF_8)),iv=cipher.getIV(),combined=new byte[iv.length+encrypted.length];
        System.arraycopy(iv,0,combined,0,iv.length);System.arraycopy(encrypted,0,combined,iv.length,encrypted.length);
        if(!preferences.edit().putString("cloud_connection",Base64.encodeToString(combined,Base64.NO_WRAP)).putBoolean("cloud_enabled",false).commit())throw new Exception("Не удалось сохранить облачное подключение");
    }
    JSONObject readCloud() throws Exception {
        String encoded=preferences.getString("cloud_connection","");if(encoded.isEmpty())return null;
        byte[] combined=Base64.decode(encoded,Base64.DEFAULT);if(combined.length<29)throw new Exception("Повреждено облачное подключение");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,java.util.Arrays.copyOfRange(combined,0,12)));
        JSONObject value=new JSONObject(new String(cipher.doFinal(java.util.Arrays.copyOfRange(combined,12,combined.length)),StandardCharsets.UTF_8));CloudChat.validate(value);return value;
    }
    private void saveSecret(String name,JSONObject value)throws Exception{
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));byte[] iv=cipher.getIV(),encrypted=cipher.doFinal(value.toString().getBytes(StandardCharsets.UTF_8)),combined=new byte[iv.length+encrypted.length];System.arraycopy(iv,0,combined,0,iv.length);System.arraycopy(encrypted,0,combined,iv.length,encrypted.length);
        if(!preferences.edit().putString(name,Base64.encodeToString(combined,Base64.NO_WRAP)).commit())throw new Exception("Не удалось сохранить защищённую настройку Gateway.");
    }
    private JSONObject readSecret(String name)throws Exception{
        String encoded=preferences.getString(name,"");if(encoded.isEmpty())return null;byte[] combined=Base64.decode(encoded,Base64.DEFAULT);if(combined.length<29)throw new Exception("Повреждена настройка Gateway.");Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,java.util.Arrays.copyOfRange(combined,0,12)));cipher.updateAAD(name.getBytes(StandardCharsets.UTF_8));return new JSONObject(new String(cipher.doFinal(java.util.Arrays.copyOfRange(combined,12,combined.length)),StandardCharsets.UTF_8));
    }
    void saveGateway(JSONObject value,boolean disable)throws Exception{new GatewayWire(value.getString("url"),value.getString("token"));saveSecret("gateway_profile",value);if(disable)preferences.edit().putBoolean("gateway_enabled",false).commit();}
    JSONObject readGateway()throws Exception{return readSecret("gateway_profile");}
    void saveGatewayPending(JSONObject value)throws Exception{saveSecret("gateway_pending",value);}
    JSONObject readGatewayPending()throws Exception{return readSecret("gateway_pending");}
    void clearGatewayPending(){preferences.edit().remove("gateway_pending").apply();}
    void saveAccount(JSONObject value)throws Exception{saveSecret("chatgpt_account",value);}
    JSONObject readAccount()throws Exception{return readSecret("chatgpt_account");}
    void clearAccount(){preferences.edit().remove("chatgpt_account").putBoolean("account_enabled",false).apply();}

    static boolean privateIp(String host) {
        return PinnedTls.privateIp(host, false);
    }
    static void validateProfile(JSONObject value, boolean token) throws Exception {
        JSONArray hosts = value.getJSONArray("hosts");
        if (hosts.length() == 0 || hosts.length() > 12 || value.getInt("port") != 48443 || !value.getString("fingerprint").matches("[a-f0-9]{64}")) throw new Exception("Некорректная ссылка подключения");
        for (int i = 0; i < hosts.length(); i++) if (!privateIp(hosts.getString(i))) throw new Exception("Нужен адрес локальной сети или Tailscale");
        if (token && !value.getString("token").matches("[A-Za-z0-9_-]{32,128}")) throw new Exception("Повреждено сохранённое подключение");
    }
    static JSONObject parsePair(String value) throws Exception {
        Uri uri = Uri.parse(value.trim());
        if (!"wileyai".equals(uri.getScheme()) || !"pair".equals(uri.getHost()) || (uri.getPath() != null && !uri.getPath().isEmpty()) || uri.getFragment() != null)
            throw new Exception("Ссылка подключения должна начинаться с wileyai://pair");
        String host = uri.getQueryParameter("host"), rest = uri.getQueryParameter("addresses"), pin = uri.getQueryParameter("fingerprint"), code = uri.getQueryParameter("code");
        String port = uri.getQueryParameter("port");
        if (host == null || pin == null || code == null || port == null || !code.matches("[A-Za-z0-9_-]{20,128}")) throw new Exception("В ссылке не хватает данных подключения");
        JSONArray hosts = new JSONArray(); hosts.put(host);
        if (rest != null && !rest.isEmpty()) for (String item : rest.split(",")) if (!item.equals(host)) hosts.put(item);
        JSONObject result = new JSONObject().put("hosts", hosts).put("port", Integer.parseInt(port)).put("fingerprint", pin).put("code", code);
        validateProfile(result, false); return result;
    }
}
