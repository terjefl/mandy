"""The site's icon: a candy cane, for the "Cane" in Mandy Cane Lane, in the pages' orange.

Pages carry it inline as data: URIs, so the public ones (which Cloudflare Access lets through by
path) show it too without opening up another path."""
import base64
import urllib.parse

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="15" fill="#e5622b"/>'
    '<g transform="rotate(-18 32 32)" fill="none" stroke-width="12">'
    '<path d="M37 54V24a9.5 9.5 0 0 0-19 0v4" stroke="#fff" stroke-linecap="round"/>'
    '<path d="M37 54V24a9.5 9.5 0 0 0-19 0v4" stroke="#a63a14" stroke-dasharray="5 6" stroke-dashoffset="1.5"/>'
    "</g></svg>"
)

# The same at 180x180 for iOS home screens (which don't take SVG), square: iOS rounds the corners
TOUCH_PNG_B64 = (
    "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"
)
TOUCH_PNG = base64.b64decode(TOUCH_PNG_B64)

# For a page's <head>; no braces, so it can sit in a str.format() template
LINKS = (
    f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{urllib.parse.quote(SVG)}">\n'
    f'<link rel="apple-touch-icon" href="data:image/png;base64,{TOUCH_PNG_B64}">\n'
)
