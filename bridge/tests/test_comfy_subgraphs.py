import copy

from bridge.core.comfycur import ui_to_api
from bridge.core.comfysubgraph import expand_subgraphs


INFO = {
    "Source": {"python_module": "nodes", "input": {"required": {}}},
    "Op": {"python_module": "nodes", "input": {"required": {
        "x": ["DATA", {}], "gain": ["INT", {"default": 2}],
    }}},
    "Sink": {"python_module": "nodes", "input": {"required": {
        "x": ["DATA", {}],
    }}},
    "PreviewAny": {"python_module": "comfy_extras.nodes_preview_any",
                   "input": {"required": {"source": ["*", {}]}}},
}


def _node(ident, kind, inputs=None, outputs=None, values=None, mode=0):
    return {"id": ident, "type": kind, "mode": mode,
            "inputs": inputs or [], "outputs": outputs or [],
            "widgets_values": values or [], "properties": {}}


def _definition(ident="def-a", inner_type="Op"):
    return {
        "id": ident, "name": ident,
        "inputs": [
            {"name": "x", "type": "DATA", "linkIds": [10]},
            {"name": "gain", "type": "INT", "linkIds": [11]},
        ],
        "outputs": [{"name": "y", "type": "DATA", "linkIds": [12]}],
        "inputNode": {"id": -10}, "outputNode": {"id": -20},
        "nodes": [_node(1, inner_type,
                        [{"name": "x", "type": "DATA", "link": 10},
                         {"name": "gain", "type": "INT",
                          "widget": {"name": "gain"}, "link": 11}],
                        [{"name": "y", "type": "DATA", "links": [12]}], [2])],
        "links": [
            {"id": 10, "origin_id": -10, "origin_slot": 0,
             "target_id": 1, "target_slot": 0, "type": "DATA"},
            {"id": 11, "origin_id": -10, "origin_slot": 1,
             "target_id": 1, "target_slot": 1, "type": "INT"},
            {"id": 12, "origin_id": 1, "origin_slot": 0,
             "target_id": -20, "target_slot": 0, "type": "DATA"},
        ],
    }


def _graph(definition=None, values=None):
    definition = definition or _definition()
    return {
        "nodes": [
            _node(100, "Source", outputs=[{"name": "out", "type": "DATA", "links": [1]}]),
            _node(5, definition["id"],
                  [{"name": "x", "type": "DATA", "link": 1}],
                  [{"name": "y", "type": "DATA", "links": [2]}], values or [7]),
            _node(200, "Sink", [{"name": "x", "type": "DATA", "link": 2}]),
        ],
        "links": [[1, 100, 0, 5, 0, "DATA"], [2, 5, 0, 200, 0, "DATA"]],
        "definitions": {"subgraphs": [definition]},
    }


def test_expansion_preserves_source_and_resolves_links_and_promoted_widget():
    graph = _graph()
    original = copy.deepcopy(graph)
    expanded = expand_subgraphs(graph)
    assert expanded["ok"] and expanded["expanded"] == 1
    assert graph == original

    converted = ui_to_api(graph, INFO)
    assert converted["ok"], converted["reason"]
    assert set(converted["graph"]) == {"100", "5:1", "200"}
    assert converted["graph"]["5:1"]["inputs"] == {
        "x": ["100", 0], "gain": 7,
    }
    assert converted["graph"]["200"]["inputs"]["x"] == ["5:1", 0]


def test_outer_link_overrides_promoted_widget_value_after_input_compression():
    graph = _graph()
    graph["nodes"].insert(1, _node(
        101, "Source", outputs=[{"name": "out", "type": "INT", "links": [3]}]))
    instance = next(n for n in graph["nodes"] if n["id"] == 5)
    # Serialized subgraph inputs are compressed: this is slot 1 here even though
    # omitted definition inputs can make positional definition indices diverge.
    instance["inputs"].append(
        {"name": "gain", "type": "INT", "widget": {"name": "gain"}, "link": 3})
    graph["links"].append([3, 101, 0, 5, 1, "INT"])

    converted = ui_to_api(graph, INFO)
    assert converted["ok"], converted["reason"]
    assert converted["graph"]["5:1"]["inputs"]["gain"] == ["101", 0]


def test_one_subgraph_input_can_fan_out_without_reusing_a_link_id():
    definition = _definition()
    definition["nodes"].append(_node(
        2, "Sink", [{"name": "x", "type": "DATA", "link": 13}]))
    definition["inputs"][0]["linkIds"].append(13)
    definition["links"].append(
        {"id": 13, "origin_id": -10, "origin_slot": 0,
         "target_id": 2, "target_slot": 0, "type": "DATA"})
    converted = ui_to_api(_graph(definition), INFO)
    assert converted["ok"], converted["reason"]
    assert converted["graph"]["5:1"]["inputs"]["x"] == ["100", 0]
    assert converted["graph"]["5:2"]["inputs"]["x"] == ["100", 0]


def test_nested_subgraph_instances_flatten_to_upstream_execution_ids():
    inner = {
        "id": "inner", "name": "inner",
        "inputs": [{"name": "x", "type": "DATA", "linkIds": [20]}],
        "outputs": [{"name": "y", "type": "DATA", "linkIds": [21]}],
        "inputNode": {"id": -10}, "outputNode": {"id": -20},
        "nodes": [_node(2, "Sink", [{"name": "x", "type": "DATA", "link": 20}],
                             [{"name": "y", "type": "DATA", "links": [21]}])],
        "links": [
            {"id": 20, "origin_id": -10, "origin_slot": 0,
             "target_id": 2, "target_slot": 0, "type": "DATA"},
            {"id": 21, "origin_id": 2, "origin_slot": 0,
             "target_id": -20, "target_slot": 0, "type": "DATA"},
        ],
    }
    outer = {
        "id": "outer", "name": "outer",
        "inputs": [{"name": "x", "type": "DATA", "linkIds": [30]}],
        "outputs": [{"name": "y", "type": "DATA", "linkIds": [31]}],
        "inputNode": {"id": -10}, "outputNode": {"id": -20},
        "nodes": [_node(3, "inner", [{"name": "x", "type": "DATA", "link": 30}],
                             [{"name": "y", "type": "DATA", "links": [31]}])],
        "links": [
            {"id": 30, "origin_id": -10, "origin_slot": 0,
             "target_id": 3, "target_slot": 0, "type": "DATA"},
            {"id": 31, "origin_id": 3, "origin_slot": 0,
             "target_id": -20, "target_slot": 0, "type": "DATA"},
        ],
        "definitions": {"subgraphs": [inner]},
    }
    graph = _graph(outer, values=[])
    graph["definitions"]["subgraphs"].append(inner)
    converted = ui_to_api(graph, INFO)
    assert converted["ok"], converted["reason"]
    assert "5:3:2" in converted["graph"]
    assert converted["graph"]["5:3:2"]["inputs"]["x"] == ["100", 0]
    assert converted["graph"]["200"]["inputs"]["x"] == ["5:3:2", 0]


def test_bypassed_subgraph_is_not_expanded_and_malformed_boundaries_refuse():
    bypassed = _graph()
    next(n for n in bypassed["nodes"] if n["id"] == 5)["mode"] = 4
    result = expand_subgraphs(bypassed)
    assert result["ok"] and result["expanded"] == 0
    assert any(n["id"] == 5 for n in result["graph"]["nodes"])

    broken = _graph()
    broken["definitions"]["subgraphs"][0]["outputs"][0]["linkIds"] = []
    result = expand_subgraphs(broken)
    assert not result["ok"] and "no inner source" in result["reason"]


def test_preview_any_is_a_stock_backend_node_not_frontend_decoration():
    graph = {
        "nodes": [
            _node(1, "Source", outputs=[{"name": "out", "type": "*", "links": [1]}]),
            _node(2, "PreviewAny", [{"name": "source", "type": "*", "link": 1}],
                  [{"name": "STRING", "type": "STRING", "links": [2]}]),
            _node(3, "Sink", [{"name": "x", "type": "DATA", "link": 2}]),
        ],
        "links": [[1, 1, 0, 2, 0, "*"], [2, 2, 0, 3, 0, "STRING"]],
    }
    converted = ui_to_api(graph, INFO)
    assert converted["ok"], converted["reason"]
    assert converted["graph"]["2"]["class_type"] == "PreviewAny"
    assert converted["graph"]["3"]["inputs"]["x"] == ["2", 0]


def test_bypassed_wildcard_node_routes_to_its_real_source():
    graph = {
        "nodes": [
            _node(1, "Source", outputs=[{"name": "out", "type": "STRING", "links": [1]}]),
            _node(2, "PreviewAny", [{"name": "source", "type": "*", "link": 1}],
                  [{"name": "STRING", "type": "STRING", "links": [2]}], mode=4),
            _node(3, "Sink", [{"name": "x", "type": "DATA", "link": 2}]),
        ],
        "links": [[1, 1, 0, 2, 0, "*"], [2, 2, 0, 3, 0, "STRING"]],
    }
    converted = ui_to_api(graph, INFO)
    assert converted["ok"], converted["reason"]
    assert "2" not in converted["graph"]
    assert converted["graph"]["3"]["inputs"]["x"] == ["1", 0]


def test_dynamic_combo_children_keep_the_frontend_wire_order_and_prefix():
    info = dict(INFO)
    info["ClipSource"] = {"python_module": "nodes", "input": {"required": {}}}
    info["TextGenerate"] = {
        "python_module": "comfy_extras.nodes_textgen",
        "input": {
            "required": {
                "clip": ["CLIP", {}],
                "prompt": ["STRING", {"default": ""}],
                "max_length": ["INT", {"default": 512}],
                "sampling_mode": ["COMFY_DYNAMICCOMBO_V3", {"options": [{
                    "key": "on", "inputs": {
                        "required": {
                            "temperature": ["FLOAT", {"default": 0.7}],
                            "top_k": ["INT", {"default": 64}],
                            "top_p": ["FLOAT", {"default": 0.95}],
                            "min_p": ["FLOAT", {"default": 0.05}],
                            "repetition_penalty": ["FLOAT", {"default": 1.05}],
                            "seed": ["INT", {"default": 0}],
                        },
                        "optional": {
                            "presence_penalty": ["FLOAT", {"default": 0.0}],
                        },
                    },
                }, {"key": "off", "inputs": {"required": {}}}]}],
            },
            "optional": {
                "image": ["IMAGE", {}], "thinking": ["BOOLEAN", {"default": False}],
                "use_default_template": ["BOOLEAN", {"default": True}],
            },
        },
        "input_order": {
            "required": ["clip", "prompt", "max_length", "sampling_mode"],
            "optional": ["image", "thinking", "use_default_template"],
        },
    }
    values = ["write a caption", 2048, "on", 0.7, 64, 0.95, 0.05,
              1.05, 1234, 0.25, False, False]
    graph = {
        "nodes": [
            _node(1, "ClipSource", outputs=[{"name": "clip", "type": "CLIP", "links": [1]}]),
            _node(2, "TextGenerate",
                  [{"name": "clip", "type": "CLIP", "link": 1}],
                  [{"name": "text", "type": "STRING", "links": []}], values),
        ],
        "links": [[1, 1, 0, 2, 0, "CLIP"]],
    }
    converted = ui_to_api(graph, info)
    assert converted["ok"], converted["reason"]
    inputs = converted["graph"]["2"]["inputs"]
    assert inputs == {
        "clip": ["1", 0], "prompt": "write a caption", "max_length": 2048,
        "sampling_mode": "on", "sampling_mode.temperature": 0.7,
        "sampling_mode.top_k": 64, "sampling_mode.top_p": 0.95,
        "sampling_mode.min_p": 0.05, "sampling_mode.repetition_penalty": 1.05,
        "sampling_mode.seed": 1234, "sampling_mode.presence_penalty": 0.25,
        "thinking": False, "use_default_template": False,
    }
