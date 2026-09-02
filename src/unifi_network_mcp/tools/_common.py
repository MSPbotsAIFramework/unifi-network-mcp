from .._json import error_envelope

NO_TOKEN = error_envelope(
    "not_configured",
    "No UniFi Network credentials. Send the X-Unifi-Host and X-Unifi-Api-Key headers.",
    False,
)
