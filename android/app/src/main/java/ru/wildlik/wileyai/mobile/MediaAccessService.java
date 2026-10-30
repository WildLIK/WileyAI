package ru.wildlik.wileyai.mobile;

import android.service.notification.NotificationListenerService;

/** Android requires an enabled notification listener for MediaSessionManager access.
 * Notification delivery is disabled in metadata. No notification content is read or retained. */
public final class MediaAccessService extends NotificationListenerService {
    // Intentionally no notification callbacks, enumeration, cancellation, or network operations.
}
