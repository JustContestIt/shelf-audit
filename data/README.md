# data/ — not in git

Customer photos, reference images and the PDF catalog are commercial data of the customer and
live only locally (or in private storage). The repository contains only ground-truth JSON
(`evals/golden/`) and these scripts.

```
python data/scripts/fetch_data.py --source "<path to the working folder>"   # photos, refs, PDF -> data/
python data/scripts/fetch_models.py [--from-dir <folder with siglip_vision.onnx>]
cd backend && python -m app.rag.ingest && python -m app.rag.build_index    # catalog.jsonl + vectors
```

Layout after fetching:

| path | what |
|---|---|
| `catalog/pdf/` | «Справочник брендов» (Figma PDF) + Frame 29–33 |
| `catalog/brands/` | raw studio mockups by brand |
| `catalog/refs_1280/` | 150 reference images, 1280 px (`<sku>__<pack>_<lang|rot>.jpg`) |
| `catalog/field_refs/` | 7 field crops from real shelves |
| `catalog/pdf_cards/` | product images extracted from the PDF (built by ingest) |
| `catalog/catalog.jsonl` | one line per reference image (built by ingest) |
| `catalog/index.npz` | vector snapshot for offline mode (built by build_index) |
| `frames/examples/` | IMG_0614…0650 — golden set frames |
| `frames/field_refs_31_08_2026/` | 28 single-product photos from 30.08 (one can / bottle on a counter) + 4 crops — raw material for field refs, not shelves |
| `models/siglip_vision.onnx` | SigLIP-base-patch16-224 vision tower |
| `uploads/` | photos received by the API (per report) |
| `MANIFEST.json` | what was copied, sizes, sha256 |
