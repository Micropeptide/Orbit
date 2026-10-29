"""The web page's own JavaScript, wherever it lives.

index.html is split so it fits the update pipeline: its CSS and JS live in app.css and
app*.js, which the page loads. A test that checks the page's JavaScript reads it through
here, so it holds whether the JS is inline in index.html (an older copy) or in those files.
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web")
PAGE = os.path.join(WEB, "index.html")


def js():
    """The page's JavaScript: any inline script, plus the app*.js files it loads."""
    html = open(PAGE, encoding="utf-8").read()
    parts = [m.group(1) for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
             if len(m.group(1).strip()) >= 20]
    for u in re.findall(r'<script[^>]*\bsrc=["\'](/app[^"\']*\.js)["\']', html):
        fp = os.path.join(WEB, u.lstrip("/"))
        if os.path.exists(fp):
            parts.append(open(fp, encoding="utf-8").read())
    return "\n".join(parts)


def page():
    """The whole page as one text: index.html, then its stylesheet and script files (for a test that asserts on any of it)."""
    html = open(PAGE, encoding="utf-8").read()
    parts = [html]
    for u in re.findall(r'(?:href|src)=["\'](/app[^"\']*\.(?:css|js))["\']', html):
        fp = os.path.join(WEB, u.lstrip("/"))
        if os.path.exists(fp):
            parts.append(open(fp, encoding="utf-8").read())
    return "\n".join(parts)
