package ru.wildlik.wileyai.mobile;
import java.util.Map;
public class AndroidTools {public record Call(String tool,Map<String,Object> arguments){} public record Result(String tool,String status,String summary,Map<String,Object> data){}}
