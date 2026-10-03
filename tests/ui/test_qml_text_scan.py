"""The QML text scanner's own edge cases.

The plain-text guard is only as strong as this scanner: a missed element, a
truncated value or a swallowed continuation is a false negative in the
security policy. These tests pin the structural rules directly, so a scanner
regression reads as a scanner failure rather than as a guard that quietly
stops seeing things.
"""

from __future__ import annotations

from support.qml_text import (
    brace_span,
    find_own_prop_value,
    find_own_text_value,
    find_text_derived_components,
    is_literal_only,
    iter_component_opens,
    iter_text_elements,
    strip_string_literals,
)


def _only_element(source: str):
    elements = list(iter_text_elements(source))
    assert len(elements) == 1, elements
    return elements[0]


# ---------------------------------------------------------------- brace spans


def test_brace_span_stops_at_the_matching_close():
    source = "Text { property: Item { } }"
    assert source[brace_span(source, source.index("{"))] == "}"


def test_brace_span_ignores_braces_inside_strings_and_comments():
    source = 'Text {\n  text: "a } b { c" // } stray\n  /* { } */\n}'
    assert brace_span(source, source.index("{")) == source.rindex("}")


def test_brace_span_handles_escaped_quotes():
    source = 'Text { text: "he said \\"}\\"" ; }'
    assert brace_span(source, source.index("{")) == source.rindex("}")


# ------------------------------------------------------------- element finding


def test_elements_are_found_with_their_lines_and_spans():
    source = 'Item {\n  Text { text: "a" }\n}\nLabel {\n  text: "b"\n}\n'
    elements = list(iter_text_elements(source))
    assert [(e.line, e.kind) for e in elements] == [(2, "Text"), (4, "Label")]
    assert elements[0].span == '{ text: "a" }'
    assert 'text: "b"' in elements[1].span


def test_text_like_types_and_enum_reads_are_not_elements():
    source = "TextField { }\nTextInput { }\nTextMetrics { }\nItem { format: Text.PlainText }\n"
    assert list(iter_text_elements(source)) == []


def test_a_nested_element_does_not_extend_the_outer_span():
    source = "Text { text: title; Item { Text { text: other } } }"
    outer, inner = list(iter_text_elements(source))
    assert outer.span == source[len("Text ") :]
    assert inner.span == "Text { text: other }"[len("Text ") :]


def test_marker_is_read_from_the_open_line_or_the_line_above():
    source = (
        '// guard:deliberate-richtext above\nText { text: "a" }\n'
        'Text { // guard:deliberate-richtext same\n text: "b" }\n'
        'Text { text: "c" }\n'
    )
    assert [e.marker for e in iter_text_elements(source)] == ["above", "same", None]


# --------------------------------------------------------------- own property


def test_own_text_is_read_for_inline_and_multiline_bindings():
    inline = _only_element("Text { textFormat: Text.PlainText; text: model.title }")
    assert find_own_text_value(inline.span).strip() == "model.title"
    multiline = _only_element("Text {\n  text: model.title + ' x'\n}")
    assert find_own_text_value(multiline.span).strip() == "model.title + ' x'"


def test_a_nested_child_text_is_not_the_elements_own():
    element = _only_element("Text {\n  Item { text: model.title }\n}")
    assert find_own_text_value(element.span) is None


def test_a_function_body_text_is_not_the_elements_own():
    element = _only_element("Text {\n  function f() { return 'x' }\n  text: 'shown'\n}")
    assert find_own_text_value(element.span).strip() == "'shown'"


def test_a_longer_property_name_ending_in_text_is_not_matched():
    element = _only_element("Text { context: model.title }")
    assert find_own_text_value(element.span) is None


def test_concatenation_continues_past_a_newline_in_both_directions():
    trailing = _only_element('Text {\n  text: "a" +\n    model.title\n}')
    assert find_own_text_value(trailing.span).strip() == '"a" +\n    model.title'
    leading = _only_element('Text {\n  text: "a"\n    + model.title\n}')
    assert find_own_text_value(leading.span).strip() == '"a"\n    + model.title'


def test_a_multiline_js_block_is_captured_whole():
    element = _only_element("Text {\n  text: {\n    var s = model.a\n    return s\n  }\n}")
    value = find_own_text_value(element.span)
    assert value is not None and "return s" in value


def test_prop_value_finds_text_format_and_ignores_children():
    element = _only_element("Text { Item { textFormat: Text.StyledText } textFormat: Text.PlainText }")
    assert find_own_prop_value(element.span, "textFormat").strip() == "Text.PlainText"


# ----------------------------------------------------------- value classifiers


def test_string_literals_are_blanked_before_marker_matching():
    stripped = strip_string_literals('text: "an album" + model.artist')
    assert "album" not in stripped
    assert "model.artist" in stripped


def test_literal_only_covers_pure_literals_not_identifiers():
    assert is_literal_only('"ALBUM"')
    assert is_literal_only('"a" + "b"')
    assert is_literal_only('"✓"')
    assert not is_literal_only("model.title")
    assert not is_literal_only("title")
    assert not is_literal_only("model['x']")


# ------------------------------------------------------------ derived components


def test_derived_components_include_declarations_and_text_rooted_files():
    source = "import QtQuick\ncomponent FooText: Text { }\nItem { FooText { text: 'x' } }\n"
    assert find_text_derived_components(source, "Plain.qml") == {"FooText": source.index("{")}
    rooted = find_text_derived_components("Text {\n  text: 'x'\n}\n", "BareText.qml")
    assert rooted == {"BareText": "Text {".index("{")}


def test_component_opens_match_instantiations_only():
    source = "component FooText: Text { }\nFooText { text: 'a' }\nItem { FooText { } }\nFooTextExtra { }\n"
    assert [line for line, _idx in iter_component_opens(source, "FooText")] == [2, 3]
