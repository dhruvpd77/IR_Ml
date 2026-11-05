"""Company mark used on the job card and the PDF."""

import os

from django.conf import settings


def brand_key(company):
    name = (company or "").strip().lower()
    if "champion" in name:
        return "champion"
    if "compair" in name:
        return "compair"
    return "ingersoll"


def brand_static(company):
    return {
        "champion": "img/champion.png",
        "compair": "img/compair.png",
        "ingersoll": "img/ir-logo.jpg",
    }[brand_key(company)]


def brand_file(company):
    filename = {
        "champion": "champion.png",
        "compair": "compair.png",
        "ingersoll": "IR_LOGO.jpg",
    }[brand_key(company)]
    path = os.path.join(settings.BASE_DIR, filename)
    if os.path.exists(path):
        return path
    static_name = brand_static(company).replace("/", os.sep)
    static_path = os.path.join(settings.BASE_DIR, "static", static_name)
    if os.path.exists(static_path):
        return static_path
    return ""
