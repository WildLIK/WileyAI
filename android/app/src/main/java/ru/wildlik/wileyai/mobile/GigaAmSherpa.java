package ru.wildlik.wileyai.mobile;

import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/**
 * Optional sherpa-onnx backend reached only through reflection so the APK builds and installs
 * without the native AAR; every failure becomes an honest "engine not installed" message.
 * All calls are serialized by GigaAmSession's worker, so this class keeps no locks.
 */
final class GigaAmSherpa implements GigaAmSession.Backend {
    private static final String PKG = "com.k2fsa.sherpa.onnx.";
    private final Map<Long, Object> recognizers = new HashMap<>();
    private long nextHandle;
    private static Class<?> type(String name) throws IOException {
        try { return Class.forName(PKG + name); }
        catch (ClassNotFoundException missing) {
            throw new IOException("Нативный движок sherpa-onnx не установлен в эту сборку. Установите движок или выберите другой распознаватель.");
        }
    }
    private static Object config(String name) throws IOException {
        return construct(type(name), 0);
    }
    /** Three-tier construction: Kotlin synthetic defaults, plain no-arg, then a full constructor with typed defaults. */
    private static Object construct(Class<?> type, int depth) throws IOException {
        Throwable shape1 = null, shape2 = null;
        try {
            for (java.lang.reflect.Constructor<?> candidate : type.getDeclaredConstructors()) {
                Class<?>[] params = candidate.getParameterTypes();
                if (params.length == 2 && params[0] == int.class && params[1].getName().equals("kotlin.jvm.internal.DefaultConstructorMarker")) {
                    candidate.setAccessible(true);
                    return candidate.newInstance(0, null); // mask 0 = every parameter keeps its Kotlin default
                }
            }
        } catch (Throwable shape) { shape1 = shape; }
        try { return type.getDeclaredConstructor().newInstance(); }
        catch (Throwable shape) { shape2 = shape; }
        for (java.lang.reflect.Constructor<?> candidate : type.getDeclaredConstructors()) {
            Class<?>[] params = candidate.getParameterTypes();
            if (params.length == 0) continue;
            if (params.length >= 1 && params[params.length - 1].getName().equals("kotlin.jvm.internal.DefaultConstructorMarker")) continue;
            try {
                Object[] args = new Object[params.length];
                for (int i = 0; i < params.length; i++) {
                    Class<?> p = params[i];
                    if (p == int.class) args[i] = 0;
                    else if (p == long.class) args[i] = 0L;
                    else if (p == float.class) args[i] = 0f;
                    else if (p == double.class) args[i] = 0d;
                    else if (p == boolean.class) args[i] = Boolean.FALSE;
                    else if (p == short.class) args[i] = (short) 0;
                    else if (p == byte.class) args[i] = (byte) 0;
                    else if (p == char.class) args[i] = (char) 0;
                    else if (p == String.class) args[i] = "";
                    else if (depth < 4) args[i] = construct(p, depth + 1);
                    else args[i] = null;
                }
                candidate.setAccessible(true);
                return candidate.newInstance(args);
            } catch (IOException nested) { throw nested; }
            catch (Throwable shape) { if (shape2 == null) shape2 = shape; }
        }
        IOException failure = new IOException("Не удалось построить конфигурацию " + type.getSimpleName() + " движка sherpa-onnx");
        if (shape1 != null) failure.initCause(shape1); else if (shape2 != null) failure.initCause(shape2);
        throw failure;
    }
    private static void set(Object target, String field, Object value) throws IOException {
        try {
            try { target.getClass().getField(field).set(target, value); return; }
            catch (NoSuchFieldException kotlinProperty) {
                String setter="set"+Character.toUpperCase(field.charAt(0))+field.substring(1);
                for (java.lang.reflect.Method method : target.getClass().getMethods()) {
                    if (method.getName().equals(setter) && method.getParameterCount()==1) {
                        method.invoke(target,value);return;
                    }
                }
                throw kotlinProperty;
            }
        } catch (Exception shape) {
            IOException failure = new IOException("Конфигурация " + target.getClass().getSimpleName() + "." + field + " не совпала с ожидаемым API sherpa-onnx");
            failure.initCause(shape); throw failure;
        }
    }
    @Override public long create(String encoder, String decoder, String joiner, String tokens, int threads) throws IOException {
        try {
            Object feature = config("FeatureConfig");
            set(feature, "sampleRate", GigaAmModel.SAMPLE_RATE);
            set(feature, "featureDim", GigaAmModel.FEATURE_DIM);
            set(feature, "dither", 0.0f);
            Object transducer = config("OfflineTransducerModelConfig");
            set(transducer, "encoder", encoder);
            set(transducer, "decoder", decoder);
            set(transducer, "joiner", joiner);
            Object model = config("OfflineModelConfig");
            set(model, "transducer", transducer);
            set(model, "modelType", "nemo_transducer");
            set(model, "tokens", tokens);
            set(model, "numThreads", threads);
            set(model, "debug", false);
            Object config = config("OfflineRecognizerConfig");
            set(config, "featConfig", feature);
            set(config, "modelConfig", model);
            set(config, "decodingMethod", "greedy_search");
            Class<?> recognizerType = type("OfflineRecognizer");
            Object recognizer = recognizerType.getDeclaredConstructor(android.content.res.AssetManager.class, config.getClass())
                .newInstance(null, config);
            synchronized (this) { long handle = ++nextHandle; recognizers.put(handle, recognizer); return handle; }
        } catch (IOException failure) { throw failure; }
        catch (OutOfMemoryError memory) { throw new IOException("Не хватило памяти для загрузки GigaAM"); }
        catch (LinkageError|ReflectiveOperationException|RuntimeException shape) {
            IOException failure = new IOException("Движок sherpa-onnx не запустился на этом устройстве");
            failure.initCause(shape); throw failure;
        }
    }
    @Override public String decode(long handle, float[] samples, int sampleRate) throws IOException {
        Object stream = null;
        try {
            Object recognizer;
            synchronized (this) { recognizer = recognizers.get(handle); }
            if (recognizer == null) throw new IOException("Распознаватель GigaAM уже освобождён");
            Class<?> recognizerType = recognizer.getClass();
            stream = recognizerType.getMethod("createStream").invoke(recognizer);
            stream.getClass().getMethod("acceptWaveform", float[].class, int.class).invoke(stream, samples, sampleRate);
            recognizerType.getMethod("decode", stream.getClass()).invoke(recognizer, stream);
            Object result = recognizerType.getMethod("getResult", stream.getClass()).invoke(recognizer, stream);
            Object text = result.getClass().getMethod("getText").invoke(result);
            return text == null ? "" : text.toString();
        } catch (IOException failure) { throw failure; }
        catch (ReflectiveOperationException|RuntimeException shape) {
            IOException failure = new IOException("Распознавание GigaAM прервалось ошибкой движка");
            failure.initCause(shape); throw failure;
        } finally {
            if (stream != null) try { stream.getClass().getMethod("release").invoke(stream); }
            catch (ReflectiveOperationException|RuntimeException ignored) { /* stream cleanup is best-effort */ }
        }
    }
    @Override public void close(long handle) {
        Object recognizer;
        synchronized (this) { recognizer = recognizers.remove(handle); }
        if (recognizer == null) return;
        try { recognizer.getClass().getMethod("release").invoke(recognizer); }
        catch (ReflectiveOperationException|RuntimeException ignored) { /* finalizer releases native memory anyway */ }
    }
}
