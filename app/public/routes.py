from fastapi import APIRouter, Request, Response
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

PUBLIC_PATHS = [
    "/",
    "/how-it-works",
    "/methodology",
    "/privacy",
    "/help",
    "/example-feedback",
    "/login",
    "/signup",
]


@router.get("/how-it-works")
def how_it_works(request: Request):
    return templates.TemplateResponse(request, "public/how_it_works.html", {})


@router.get("/methodology")
def methodology(request: Request):
    return templates.TemplateResponse(request, "public/methodology.html", {})


@router.get("/privacy")
def privacy(request: Request):
    return templates.TemplateResponse(request, "public/privacy.html", {})


@router.get("/help")
def help_faq(request: Request):
    return templates.TemplateResponse(request, "public/help.html", {})


@router.get("/example-feedback")
def example_feedback(request: Request):
    return templates.TemplateResponse(request, "public/example_feedback.html", {})


@router.get("/robots.txt")
def robots_txt(request: Request):
    base = str(request.base_url).rstrip("/")
    lines = [
        "User-agent: *",
        "Disallow: /settings",
        "Disallow: /history",
        "Disallow: /progress",
        "Disallow: /practice",
        "Disallow: /goals",
        "Disallow: /vocab",
        "Disallow: /documents",
        "Disallow: /drafts",
        "Disallow: /verify-email",
        "Disallow: /reset-password",
        "Disallow: /forgot-password",
        "",
        f"Sitemap: {base}/sitemap.xml",
        "",
    ]
    return Response("\n".join(lines), media_type="text/plain")


@router.get("/sitemap.xml")
def sitemap_xml(request: Request):
    base = str(request.base_url).rstrip("/")
    urls = "".join(f"<url><loc>{base}{path}</loc></url>" for path in PUBLIC_PATHS)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>"
    )
    return Response(xml, media_type="application/xml")
