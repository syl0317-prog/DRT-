"""Presentation-only widget state, kept outside Streamlit's widget cleanup keys."""
import hashlib
import inspect
import json
from contextlib import contextmanager
from datetime import datetime
from functools import wraps

import streamlit as _st


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


class PersistentUI:
    """Delegate UI calls; use durable shadow values without global monkey-patching."""
    WIDGETS = {"selectbox", "multiselect", "radio", "checkbox", "number_input", "slider",
               "time_input", "date_input", "text_input"}

    def __init__(self, target=None):
        self.target = target or _st

    def __enter__(self):
        self.target.__enter__()
        return self

    def __exit__(self, *args):
        return self.target.__exit__(*args)

    def __getattr__(self, name):
        original = getattr(self.target, name)
        if name == "columns":
            return lambda *a, **k: [PersistentUI(col) for col in original(*a, **k)]
        if name not in self.WIDGETS:
            return original

        @wraps(original)
        def widget(*args, **kwargs):
            scope = _st.session_state.get("ui_scope", "global")
            label = kwargs.get("label", args[0] if args else name)
            key = kwargs.get("key") or "ui_"+signature([scope, name, label])[:20]
            kwargs["key"] = key
            saved = _st.session_state.setdefault("ui_saved_values", {})
            if key not in _st.session_state and key in saved:
                value = saved[key]
                options = kwargs.get("options", args[1] if len(args) > 1 else None)
                if name in ("selectbox", "radio", "multiselect") and options is not None:
                    options = list(options)
                    if name == "multiselect":
                        value = [v for v in value if v in options]
                    elif value not in options:
                        value = None
                if value is not None:
                    # Restore through initial widget values, not a simultaneous
                    # session-state assignment + default (which Streamlit warns about).
                    bound = inspect.signature(original).bind_partial(*args, **kwargs)
                    if name in ("selectbox", "radio"):
                        bound.arguments["index"] = options.index(value)
                    elif name == "multiselect":
                        bound.arguments["default"] = value
                    else:
                        bound.arguments["value"] = value
                    args, kwargs = bound.args, bound.kwargs
            result = original(*args, **kwargs)
            saved[key] = result
            return result
        return widget


persistent_ui = PersistentUI()


@contextmanager
def scope(name):
    previous = _st.session_state.get("ui_scope", "global")
    _st.session_state["ui_scope"] = name
    try:
        yield
    finally:
        _st.session_state["ui_scope"] = previous


def remember_result(key, inputs, value, source):
    record = dict(signature=signature(inputs), inputs=inputs, value=value, source=source,
                  created_at=datetime.now().astimezone().isoformat(), result_type="research_simulation")
    _st.session_state[key] = record
    return record


def matching_result(key, inputs):
    record = _st.session_state.get(key)
    return record if record and record["signature"] == signature(inputs) else None
