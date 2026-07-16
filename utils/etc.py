def resolve_device(request):
    """Look up the requesting Device from the X-Device-ID header, scoped to
    the authenticated user so one account can't attribute writes to another
    account's device."""
    device_id = request.headers.get("X-Device-ID")
    if not device_id:
        return None
    from accounts.models import Device

    return Device.objects.filter(pk=device_id, user=request.user).first()
