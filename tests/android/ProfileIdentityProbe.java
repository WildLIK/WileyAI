package ru.wildlik.wileyai.mobile;

public class ProfileIdentityProbe {
    public static void main(String[] args){
        check(ProfileIdentity.answer("Как меня зовут?", "Родион", "Зебра").contains("Родион"));
        check(ProfileIdentity.answer("Как ко мне обращаться?", "Родион", "Зебра").contains("Зебра"));
        check(!ProfileIdentity.answer("Как меня зовут?", "", "Зебра").contains("Зебра"));
        check(ProfileIdentity.answer("Как меня зовут?", "", "Зебра").contains("не указали"));
        check(ProfileIdentity.answer("Как ко мне обращаться?", "Родион", "").contains("не указали"));
        check(ProfileIdentity.answer("Как мне обращаться к тебе?", "Родион", "Зебра")==null);
        check(ProfileIdentity.answer("Если спрошу как меня зовут", "Родион", "Зебра")==null);
    }
    private static void check(boolean condition){if(!condition)throw new AssertionError();}
}
