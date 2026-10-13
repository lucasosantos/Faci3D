

def test_glass_paints_translucent_and_undoes(monkeypatch):
    # The library's glass carries opacity: painting stamps it, an opaque
    # repaint clears it, and the eyedropper samples it.
    from PySide6.QtGui import QVector3D
    from core.scene import Scene
    from core.history import History
    from core.history import (CompoundCommand, SetFaceColorCommand,
                              SetFaceOpacityCommand, SetFaceTextureCommand)
    scene = Scene()
    hist = History(scene)
    f = scene.mesh.add_face([QVector3D(0, 0, 0), QVector3D(1, 0, 0),
                             QVector3D(1, 1, 0), QVector3D(0, 1, 0)])
    hist.execute(CompoundCommand([
        SetFaceTextureCommand([f], {"path": "glass.png", "sw": 1, "sh": 1}),
        SetFaceOpacityCommand([f], 0.45),
    ]))
    assert f.attrs["opacity"] == 0.45
    hist.execute(CompoundCommand([
        SetFaceColorCommand([f], (1.0, 0.0, 0.0)),
        SetFaceTextureCommand([f], None),
        SetFaceOpacityCommand([f], None),   # opaque paint clears the glass
    ]))
    assert "opacity" not in f.attrs
    assert hist.undo() and f.attrs["opacity"] == 0.45
    assert hist.undo() and "opacity" not in f.attrs


# ---- RAL Classic: paint you can specify --------------------------------------

def _ral():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return json.loads((root / "resources" / "colors" / "ral.json")
                      .read_text(encoding="utf-8"))


def test_the_ral_palette_is_complete_and_well_formed():
    data = _ral()
    colors = [c for f in data["families"] for c in f["colors"]]
    assert len(colors) == 213, "RAL Classic is 213 colours"
    codes = [c["code"] for c in colors]
    assert len(set(codes)) == len(codes), "a code appears twice"
    assert all(c["code"].startswith("RAL ") for c in colors)
    for c in colors:
        assert len(c["rgb"]) == 3
        assert all(0.0 <= v <= 1.0 for v in c["rgb"]), c["code"]
        assert c["name"] and c["name_es"], c["code"]
        assert c["name"][0].isupper(), c["code"]   # a name, not a fragment


def test_a_few_ral_colours_are_the_ones_the_standard_says():
    # Spot checks against the standard, so a bad parse or a shifted row is
    # caught: white, black, the light grey every façade is painted, and the
    # traffic red of a fire door.
    by = {c["code"]: c for f in _ral()["families"] for c in f["colors"]}

    def hex_of(code):
        return "".join("%02X" % round(v * 255) for v in by[code]["rgb"])

    assert hex_of("RAL 9010") == "F7F9EF"      # Pure white
    assert hex_of("RAL 9005") == "0A0A0D"      # Jet black
    assert hex_of("RAL 7035") == "CBD0CC"      # Light grey
    assert hex_of("RAL 3020") == "C1121C"      # Traffic red
    assert by["RAL 7035"]["name_es"] == "Gris claro"
    assert by["RAL 3020"]["name_es"] == "Rojo tráfico"


def test_every_ral_colour_is_in_exactly_one_family():
    data = _ral()
    ids = [f["id"] for f in data["families"]]
    assert len(set(ids)) == len(ids) == 9
    seen = set()
    for fam in data["families"]:
        assert fam["name"] and fam["name_es"], fam["id"]
        for c in fam["colors"]:
            assert c["code"] not in seen, c["code"]
            seen.add(c["code"])
        # A family holds one RAL thousand-range and nothing else.
        assert len({c["code"][4] for c in fam["colors"]}) == 1, fam["id"]
