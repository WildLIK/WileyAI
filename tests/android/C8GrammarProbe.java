import java.util.List;
import ru.wildlik.wileyai.mobile.AndroidTools;
import ru.wildlik.wileyai.mobile.StructuredActionAdapter;

/** Emits the production grammar without invoking Android or a model. */
public final class C8GrammarProbe {
    public static void main(String[] args) {
        var tools = switch (args[0]) {
            case "empty" -> List.<AndroidTools.Tool>of();
            case "one" -> List.of(AndroidTools.get("get_time"));
            case "multiple" -> List.of(AndroidTools.get("get_time"), AndroidTools.get("set_volume"));
            default -> throw new IllegalArgumentException(args[0]);
        };
        System.out.print(StructuredActionAdapter.grammar(tools, 1));
    }
}
