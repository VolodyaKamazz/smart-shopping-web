def image_of(product):
    url = (getattr(product, "image_url", "") or "").strip() if product is not None else ""
    return url if url.lower().startswith(("http://", "https://")) else ""
