"""Faithfully flatten ComfyUI frontend subgraphs into an ordinary UI graph.

ComfyUI's server accepts an API prompt, not frontend subgraph definitions.  The
frontend therefore expands each active subgraph instance and resolves its boundary
links before submitting.  MOT Deck's discovered-workflow converter has to do the
same job; treating a UUID node type as a missing custom node is both unhelpful and
incorrect.

The rules here are derived from the pinned ComfyUI frontend 1.49.6 sources
(`ExecutableNodeDTO.ts`, `SubgraphNode.ts`, and `executionUtil.ts`), then exercised
against the seven subgraph templates shipped by workflow-templates 0.11.48.

This module does not mutate its input.  It returns a canonical object-link graph for
the existing converter, or an explicit refusal when a boundary is malformed.  A
plausible but incorrectly wired generation is worse than a refusal.
"""
from __future__ import annotations

import copy
from typing import Any


def _link_obj(raw: Any) -> "dict | None":
    if isinstance(raw, (list, tuple)) and len(raw) >= 5:
        return {
            "id": raw[0], "origin_id": raw[1], "origin_slot": raw[2],
            "target_id": raw[3], "target_slot": raw[4],
            "type": raw[5] if len(raw) > 5 else None,
        }
    if isinstance(raw, dict) and raw.get("id") is not None:
        return dict(raw)
    return None


def _definitions(graph: dict) -> "tuple[dict, str | None]":
    found: dict[str, dict] = {}

    def visit(raw_defs: Any) -> "str | None":
        if raw_defs is None:
            return None
        if not isinstance(raw_defs, list):
            return "subgraph definitions are not a list"
        for raw in raw_defs:
            if not isinstance(raw, dict):
                return "a subgraph definition is not an object"
            ident = raw.get("id")
            if not isinstance(ident, str) or not ident:
                return "a subgraph definition has no stable id"
            if ident in found and found[ident] != raw:
                return f"subgraph definition {ident} is declared more than once"
            found.setdefault(ident, raw)
            nested = ((raw.get("definitions") or {}).get("subgraphs")
                      if isinstance(raw.get("definitions"), dict) else None)
            err = visit(nested)
            if err:
                return err
        return None

    defs = ((graph.get("definitions") or {}).get("subgraphs")
            if isinstance(graph.get("definitions"), dict) else None)
    return found, visit(defs)


def _unique_name(prefix: str, used: set) -> str:
    candidate = prefix
    suffix = 2
    while candidate in used:
        candidate = f"{prefix}:{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _slot_name(node: dict, which: str, index: Any) -> "str | None":
    try:
        slot = (node.get(which) or [])[int(index)]
    except (IndexError, TypeError, ValueError):
        return None
    name = slot.get("name") if isinstance(slot, dict) else None
    return name if isinstance(name, str) and name else None


def _named_slots(rows: Any, label: str) -> "tuple[dict, str | None]":
    if not isinstance(rows, list):
        return {}, f"subgraph {label} are not a list"
    out = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            return {}, f"a subgraph {label[:-1]} is not an object"
        name = row.get("name")
        if not isinstance(name, str) or not name:
            return {}, f"a subgraph {label[:-1]} has no name"
        if name in out:
            return {}, f"subgraph {label[:-1]} name {name!r} is ambiguous"
        out[name] = (index, row)
    return out, None


def _boundary_links(definition: dict, io: str, slot: int) -> list:
    """Boundary links in the authored slot order, not incidental JSON order."""
    rows = definition.get("inputs" if io == "input" else "outputs") or []
    if slot >= len(rows) or not isinstance(rows[slot], dict):
        return []
    wanted = rows[slot].get("linkIds") or []
    by_id = {}
    for raw in definition.get("links") or []:
        link = _link_obj(raw)
        if link is not None:
            by_id[link["id"]] = link
    return [by_id[x] for x in wanted if x in by_id]


def _is_promoted_widget(definition: dict, slot: int, nodes: dict) -> bool:
    input_id = (definition.get("inputNode") or {}).get("id", -10)
    for link in _boundary_links(definition, "input", slot):
        if link.get("origin_id") != input_id:
            continue
        target = nodes.get(link.get("target_id"))
        try:
            target_input = (target.get("inputs") or [])[int(link.get("target_slot"))]
        except (AttributeError, IndexError, TypeError, ValueError):
            continue
        if isinstance(target_input, dict) and isinstance(target_input.get("widget"), dict):
            return True
    return False


def expand_subgraphs(graph: dict) -> dict:
    """Return ``{ok, graph, reason, expanded}`` for a frontend UI graph.

    Active instances are expanded recursively.  Muted and bypassed instances stay in
    place so the existing converter can apply ComfyUI's ordinary mute/bypass rules.
    """
    if not isinstance(graph, dict):
        return {"ok": False, "graph": {}, "reason": "the template is not an object",
                "expanded": 0}
    definitions, err = _definitions(graph)
    if err:
        return {"ok": False, "graph": {}, "reason": err, "expanded": 0}
    if not definitions:
        return {"ok": True, "graph": copy.deepcopy(graph), "reason": None,
                "expanded": 0}

    work = copy.deepcopy(graph)
    nodes = list(work.get("nodes") or [])
    links = []
    for raw in work.get("links") or []:
        link = _link_obj(raw)
        if link is None:
            return {"ok": False, "graph": {}, "reason": "the graph has a malformed link",
                    "expanded": 0}
        links.append(link)
    work["links"] = links
    ancestry = {n.get("id"): () for n in nodes if isinstance(n, dict)}
    used_nodes = {n.get("id") for n in nodes if isinstance(n, dict)}
    used_links = {l.get("id") for l in links}
    expanded = 0

    while True:
        instance = next((n for n in nodes if isinstance(n, dict)
                         and str(n.get("type")) in definitions
                         and n.get("mode") not in (2, 4)), None)
        if instance is None:
            break
        instance_id = instance.get("id")
        def_id = str(instance.get("type"))
        parents = ancestry.get(instance_id, ())
        if def_id in parents:
            return {"ok": False, "graph": {},
                    "reason": f"subgraph {def_id} contains a recursive instance",
                    "expanded": expanded}
        definition = definitions[def_id]
        raw_inner = definition.get("nodes")
        if not isinstance(raw_inner, list) or not all(isinstance(n, dict) for n in raw_inner):
            return {"ok": False, "graph": {},
                    "reason": f"subgraph {def_id} has a malformed node list",
                    "expanded": expanded}
        inner_by_id = {n.get("id"): n for n in raw_inner}
        if len(inner_by_id) != len(raw_inner) or None in inner_by_id:
            return {"ok": False, "graph": {},
                    "reason": f"subgraph {def_id} has ambiguous node ids",
                    "expanded": expanded}
        def_inputs, err = _named_slots(definition.get("inputs") or [], "inputs")
        if err:
            return {"ok": False, "graph": {}, "reason": err, "expanded": expanded}
        def_outputs, err = _named_slots(definition.get("outputs") or [], "outputs")
        if err:
            return {"ok": False, "graph": {}, "reason": err, "expanded": expanded}

        instance_inputs = instance.get("inputs") or []
        instance_outputs = instance.get("outputs") or []
        if not isinstance(instance_inputs, list) or not isinstance(instance_outputs, list):
            return {"ok": False, "graph": {},
                    "reason": f"subgraph instance {instance_id} has malformed slots",
                    "expanded": expanded}
        in_names = {}
        for index, row in enumerate(instance_inputs):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                return {"ok": False, "graph": {},
                        "reason": f"subgraph instance {instance_id} has an unnamed input",
                        "expanded": expanded}
            if row["name"] in in_names:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph instance {instance_id} has ambiguous input names",
                        "expanded": expanded}
            in_names[row["name"]] = index
        out_names = {}
        for index, row in enumerate(instance_outputs):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                return {"ok": False, "graph": {},
                        "reason": f"subgraph instance {instance_id} has an unnamed output",
                        "expanded": expanded}
            if row["name"] in out_names:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph instance {instance_id} has ambiguous output names",
                        "expanded": expanded}
            out_names[row["name"]] = index

        incoming = {}
        outgoing = []
        retained = []
        for link in links:
            if link.get("target_id") == instance_id:
                name = _slot_name(instance, "inputs", link.get("target_slot"))
                if not name or name not in def_inputs:
                    return {"ok": False, "graph": {},
                            "reason": (f"subgraph instance {instance_id} has an input link "
                                       "whose slot cannot be resolved"), "expanded": expanded}
                if name in incoming:
                    return {"ok": False, "graph": {},
                            "reason": f"subgraph input {name!r} has more than one outer link",
                            "expanded": expanded}
                incoming[name] = link
                continue
            if link.get("origin_id") == instance_id:
                name = _slot_name(instance, "outputs", link.get("origin_slot"))
                if not name or name not in def_outputs:
                    return {"ok": False, "graph": {},
                            "reason": (f"subgraph instance {instance_id} has an output link "
                                       "whose slot cannot be resolved"), "expanded": expanded}
                outgoing.append((name, link))
                continue
            retained.append(link)

        id_map = {}
        new_nodes = []
        child_parents = parents + (def_id,)
        for inner in raw_inner:
            new_id = f"{instance_id}:{inner['id']}"
            if new_id in used_nodes:
                return {"ok": False, "graph": {},
                        "reason": f"flattened node id {new_id!r} collides with the graph",
                        "expanded": expanded}
            used_nodes.add(new_id)
            id_map[inner["id"]] = new_id
            clone = copy.deepcopy(inner)
            clone["id"] = new_id
            new_nodes.append(clone)
            ancestry[new_id] = child_parents

        def_links = []
        for raw in definition.get("links") or []:
            link = _link_obj(raw)
            if link is None:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph {def_id} has a malformed link",
                        "expanded": expanded}
            def_links.append(link)
        input_node_id = (definition.get("inputNode") or {}).get("id", -10)
        output_node_id = (definition.get("outputNode") or {}).get("id", -20)

        new_links = []
        # Ordinary interior links.
        for link in def_links:
            if link.get("origin_id") == input_node_id or link.get("target_id") == output_node_id:
                continue
            if link.get("origin_id") not in id_map or link.get("target_id") not in id_map:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph {def_id} has a link to an unknown inner node",
                        "expanded": expanded}
            clone = dict(link)
            clone["id"] = _unique_name(
                f"__sglink__:{instance_id}:{link['id']}", used_links)
            clone["origin_id"] = id_map[link["origin_id"]]
            clone["target_id"] = id_map[link["target_id"]]
            new_links.append(clone)

        raw_values = instance.get("widgets_values")
        value_map = raw_values if isinstance(raw_values, dict) else None
        values = list(raw_values or []) if not isinstance(raw_values, dict) else []
        value_pos = 0
        for name, (slot, _row) in def_inputs.items():
            boundaries = [x for x in _boundary_links(definition, "input", slot)
                          if x.get("origin_id") == input_node_id]
            promoted = _is_promoted_widget(definition, slot, inner_by_id)
            has_value = False
            value = None
            if promoted:
                if value_map is not None and name in value_map:
                    value, has_value = value_map[name], True
                elif value_pos < len(values):
                    value, has_value = values[value_pos], True
                value_pos += 1
            outer = incoming.get(name)
            primitive_id = None
            if outer is None and promoted and has_value:
                primitive_id = _unique_name(f"{instance_id}:@input:{slot}", used_nodes)
                new_nodes.append({
                    "id": primitive_id, "type": "PrimitiveNode", "mode": 0,
                    "widgets_values": [copy.deepcopy(value)], "inputs": [],
                    "outputs": [{"name": name, "type": _row.get("type"), "links": []}],
                })
                ancestry[primitive_id] = child_parents
            for count, boundary in enumerate(boundaries):
                target = boundary.get("target_id")
                if target not in id_map:
                    return {"ok": False, "graph": {},
                            "reason": f"subgraph input {name!r} targets an unknown node",
                            "expanded": expanded}
                if outer is None and primitive_id is None:
                    continue
                clone = dict(boundary)
                clone["id"] = (outer["id"] if outer is not None and count == 0 else
                               _unique_name(f"__sgin__:{instance_id}:{name}:{count}",
                                            used_links))
                used_links.add(clone["id"])
                clone["origin_id"] = outer["origin_id"] if outer is not None else primitive_id
                clone["origin_slot"] = outer.get("origin_slot", 0) if outer is not None else 0
                clone["target_id"] = id_map[target]
                new_links.append(clone)

        # Mirror ComfyUI's `.at(0)` output resolution: the definition's authored
        # linkIds order chooses the boundary source.  Duplicate links with the same
        # source are valid and occur in the pinned SD3.5 template.
        for name, outer in outgoing:
            slot, _row = def_outputs[name]
            candidates = [x for x in _boundary_links(definition, "output", slot)
                          if x.get("target_id") == output_node_id]
            if not candidates:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph output {name!r} has no inner source",
                        "expanded": expanded}
            source = candidates[0]
            if source.get("origin_id") not in id_map:
                return {"ok": False, "graph": {},
                        "reason": f"subgraph output {name!r} comes from an unknown node",
                        "expanded": expanded}
            clone = dict(outer)
            clone["origin_id"] = id_map[source["origin_id"]]
            clone["origin_slot"] = source.get("origin_slot", 0)
            retained.append(clone)

        links = retained + new_links
        nodes = [n for n in nodes if n is not instance] + new_nodes
        # Rebuild serialized slot link ids from the canonical links.  The converter
        # reads input links, while bypass resolution also needs accurate output links.
        in_link = {(l.get("target_id"), l.get("target_slot")): l["id"] for l in links}
        out_links: dict[tuple, list] = {}
        for link in links:
            out_links.setdefault((link.get("origin_id"), link.get("origin_slot")), []).append(
                link["id"])
        for node in nodes:
            for index, slot in enumerate(node.get("inputs") or []):
                if isinstance(slot, dict):
                    slot["link"] = in_link.get((node.get("id"), index))
            for index, slot in enumerate(node.get("outputs") or []):
                if isinstance(slot, dict):
                    ids = out_links.get((node.get("id"), index), [])
                    slot["links"] = ids or None
        expanded += 1
        if len(nodes) > 10_000 or expanded > 1_000:
            return {"ok": False, "graph": {},
                    "reason": "subgraph expansion exceeds the safe graph bound",
                    "expanded": expanded}

    work["nodes"] = nodes
    work["links"] = links
    return {"ok": True, "graph": work, "reason": None, "expanded": expanded}
