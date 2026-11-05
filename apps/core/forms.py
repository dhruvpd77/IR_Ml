def style_form(form):
    for field in form.fields.values():
        widget = field.widget
        input_type = getattr(widget, "input_type", "")
        if input_type == "checkbox":
            widget.attrs["class"] = "checkbox-input"
        elif input_type == "file":
            widget.attrs["class"] = "file-input"
        else:
            widget.attrs["class"] = (widget.attrs.get("class", "") + " field-input").strip()
    return form
