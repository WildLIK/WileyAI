package ru.wildlik.wileyai.mobile;

/** Common contextual recovery dialog. */
final class SetupAction {
    private SetupAction() {}

    static void show(MobileUi ui, String title, String detail, String primary, Runnable action,
                     String secondary, Runnable alternative) {
        var dialog = ui.dialog().setTitle(title).setMessage(detail).setNegativeButton("Отмена", null)
                .setPositiveButton(primary, (d, w) -> action.run());
        if (alternative != null) dialog.setNeutralButton(secondary, (d, w) -> alternative.run());
        dialog.show();
    }
}
