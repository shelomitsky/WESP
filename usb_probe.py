"""Decode a bounded WLED state/info JSON response."""
import json

DEFAULT_PORT = None

def decode_reply(data):
    text = data.decode('utf-8', errors='replace')
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char != '{':
            continue
        try:
            value, _ = decoder.raw_decode(text, offset)
        except ValueError:
            continue
        if (isinstance(value, dict) and isinstance(value.get('state'), dict)
                and isinstance(value.get('info'), dict)):
            return value
    return None
