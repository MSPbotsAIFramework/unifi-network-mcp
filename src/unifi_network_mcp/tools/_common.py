from .._json import error_envelope

NO_TOKEN = error_envelope(
    "not_configured",
    "No UniFi Network credentials. Send the X-Unifi-Api-Key and X-Unifi-Console-Id headers.",
    False,
)
