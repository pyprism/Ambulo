from celery import shared_task


@shared_task(name="social.notify_friend_geofence_event")
def notify_friend_geofence_event(actor_user_id, place_name, event_type):
    """Tell an actor's accepted friends (who they share location with) that
    they entered/exited a place.

    Push dispatch (APNs/FCM) isn't wired in this deployment. This in-app Notification row is the MVP substitute; swap
    in a real push send here once device push tokens exist.
    """
    from accounts.models import User
    from utils.enums import NotificationType

    from .models import Friendship, Notification

    try:
        actor = User.objects.get(pk=actor_user_id)
    except User.DoesNotExist:
        return 0

    notifications = []
    friendships = (
        Friendship.objects.involving(actor)
        .accepted()
        .select_related("requester", "addressee")
    )
    for friendship in friendships:
        friend = friendship.other(actor)
        actor_shares = (
            friendship.requester_shares_location
            if friendship.requester_id == actor.pk
            else friendship.addressee_shares_location
        )
        if not actor_shares:
            continue
        notifications.append(
            Notification(
                user=friend,
                notification_type=NotificationType.friend_geofence,
                payload={
                    "friend_username": actor.username,
                    "place": place_name,
                    "event": event_type,
                },
            )
        )
    Notification.objects.bulk_create(notifications)
    return len(notifications)
