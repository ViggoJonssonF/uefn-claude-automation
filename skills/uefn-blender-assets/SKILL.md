---
name: uefn-blender-assets
description: Conventions for creating custom 3D assets in Blender and bringing them into UEFN - procedural bpy build scripts, export as centimetre FBX, UEFN import via AssetImportTask with verified dimensions, parametric UEFN materials + instances, LODs/Nanite/collision, previews and a validation record - distilled from a pipeline GPT Astra used to ship a dozen assets for a real island. Asset creation is TOKEN-EXPENSIVE (one pair of signs took ~34M Codex tokens): only on the user's explicit request, normally delegated to Codex via codex_delegate.py. Read before planning, briefing or reviewing any new mesh.
---

# Custom assets: Blender → UEFN

## Cost rule (read first)
A new asset is the most expensive thing in the workflow (the first sign pair: ~330 tool calls,
~34M tokens). Never create one because it "would look nicer". Use existing project/Fortnite
assets or a primitive placeholder unless the user explicitly asked for a new asset. When they
did: the director records `gauntlet.py assets approve --count N --max-tokens T --max-steps S`
and the work goes to Codex with `codex_delegate.py --asset-job` (runs on the user's Codex usage,
refuses without that approval, kills the job at the step cap).

Prerequisites on the machine: Blender running with the **Blender MCP Bridge** add-on listening on
`127.0.0.1:9876` (djeada/blender-mcp-server; Codex already has it configured as `blender`), UEFN open.

## Work folder layout (one per asset family, inside the project's Content)
```
<Name>Work/
  build_<name>.py          procedural bpy build - reproducible, refuses to overwrite a finished scene
  finalize_blender.py      cleanup, UVs, collision, naming
  export_<name>.py         FBX export
  import_uefn.py           UEFN Python import + LODs + materials + dimension check
  materials_uefn.py        UEFN materials/instances
  Delivery/                .blend, *.fbx, preview PNGs, materials.json, validation_*.json, README_SV.md
```

## Blender side
- Metric scene, scale 1; origin at floor level, centred under the object (or where the brief says
  placement anchors are). Rotation 0, scale applied. Name meshes `SM_<Name>`.
- Keep editable sources (text curves, modifiers) in a `*_SOURCE_Editable` collection; build the
  export mesh from evaluated copies; join; remove doubles; triangulate; dissolve degenerates;
  recalc normals.
- UVs: `UV0` surface, `UV1` lightmap (separate pack). Bevel + weighted-normal modifiers for rounded,
  stylised shapes; match your island's existing assets.
- Collision: simple `UCX_SM_<Name>_00…` boxes when the asset needs collision; none otherwise.
- Materials: few slots, named `M_<Name>_<Part>`; write their colour/roughness/emission to
  `materials.json` so UEFN can rebuild them (FBX does not carry Blender node materials).
- Preview: render front + angle PNGs in a separate preview collection that is NOT exported.

## FBX export (centimetres, proven settings)
Temporarily set `scene.unit_settings.scale_length = 0.01`, export copies scaled ×100:
`export_scene.fbx(use_selection=True, object_types={'MESH'}, axis_forward='Y', axis_up='Z',
global_scale=1, apply_unit_scale=True, apply_scale_options='FBX_SCALE_NONE', use_space_transform=True,
bake_space_transform=True, use_mesh_modifiers=True, mesh_smooth_type='FACE', add_leaf_bones=False,
bake_anim=False)`, then restore. Re-import the FBX in Blender to check dimensions/rotation/scale
and write `validation_geometry.json` (`name`, `dimensions_cm`, `materials`).

## UEFN side (Python via the 8765 listener, or Epic's MCP where it covers it)
- `AssetImportTask` + `FbxFactory` + `FbxImportUI`: static mesh only, no materials/textures/anims,
  `combine_meshes`, `convert_scene`, `convert_scene_unit`, uniform scale 1, rotation 0, import
  normals+tangents, `auto_generate_collision=False`. Destination `/<Project>/Meshes/<Family>`.
  Refuse to overwrite an existing asset.
- Nanite off (`StaticMeshEditorSubsystem.set_nanite_settings`), 3 LODs (100/95/90 % triangles,
  screen sizes 1/0.2/0.08), min LOD 0 for all quality levels; remove auto collision unless UCX.
- Materials: parent material with parameters `Color` / `Roughness` / `GlowStrength` built with
  `MaterialEditingLibrary`, then `MI_` instances per variant; assign by slot index. (Do not compile
  materials with Sine/Cosine graphs through Python - known crash.)
- **Verify**: imported bounding-box dimensions match `validation_geometry.json` within 0.03 cm;
  write `validation_uefn.json` (dims, LOD count, collision hulls, nanite, material paths).
- Save by full object path; never delete-then-recompile Verse in the same session.

## Done means
FBX + .blend + previews in `Delivery/`, UEFN assets exist with verified dimensions, validation JSONs
written, a short `README_SV.md` (what, size, anchors, materials, what is NOT verified), and a
screenshot of the asset placed/captured inside UEFN for the visual critic.
