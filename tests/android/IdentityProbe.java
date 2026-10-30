import ru.wildlik.wileyai.mobile.*;
import java.nio.file.*;
import java.util.*;
import java.io.*;

public class IdentityProbe {
    public static void main(String[] args)throws Exception{
        Map<?,?> fixture=(Map<?,?>)StrictJson.parse(Files.readString(Path.of(args[0])));boolean accepted;
        try{JwtIdentity.validate((String)fixture.get("token"),(String)fixture.get("client"),(String)fixture.get("nonce"),(String)fixture.get("subject"),(Map<?,?>)fixture.get("jwks"),((Number)fixture.get("now")).longValue());accepted=true;}catch(Exception expected){accepted=false;}
        if(accepted!=(Boolean)fixture.get("accepted"))throw new AssertionError("OIDC identity acceptance mismatch");
        List<String> events=new ArrayList<>();ProviderSse.read(new StringReader("event: response.output_text.delta\ndata: {\"type\":\"response.output_text.delta\"}\n\nevent: response.completed\ndata: {\"type\":\"response.completed\"}\n\n"),events::add);if(events.size()!=2)throw new AssertionError();
        try{ProviderSse.read(new StringReader("data: unfinished"),s->{});throw new AssertionError();}catch(IOException expected){}
        System.out.println("IDENTITY_AND_SSE_OK");
    }
}
