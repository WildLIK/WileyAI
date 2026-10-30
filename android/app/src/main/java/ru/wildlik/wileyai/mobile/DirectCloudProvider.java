package ru.wildlik.wileyai.mobile;

import org.json.JSONObject;

/** A documented keyless endpoint, configured explicitly. No hidden proxy or invented free service. */
final class DirectCloudProvider extends OfficialAPIProvider {
    DirectCloudProvider(JSONObject config)throws Exception{super(config);if(!config.optString("key").isEmpty())throw new IllegalArgumentException("Источник требует credential: выберите API или поддержанный вход аккаунтом.");}
    public Kind kind(){return Kind.DIRECT_CLOUD;}
}
