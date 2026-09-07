# Report chart map

## Median inference latency

- Question: How do the original eager model, fused TorchScript, and ONNX Runtime compare as CPU threads increase?
- Family: Comparison and ranking; grouped vertical bar.
- Fields: thread count, backend, median milliseconds, mean milliseconds, p95 milliseconds, FPS, relative speedup.
- Claim: TorchScript is consistently fastest on the measured x86 host and reaches a 2.34x speedup at four threads.
- Palette: Categorical palette with direct backend legend; color is reinforced by grouped position and exact table values.
- Source: `results/current_x86_threads*/benchmark.json`, aggregated in `results/README.md`.

## Deployment artifact size

- Question: How much smaller are the deployment artifacts than the original training checkpoint?
- Family: Comparison and ranking; single-series vertical bar.
- Fields: artifact name, bytes, KiB, role.
- Claim: Removing training-only state and freezing the graph reduces the copyable model from 42.94 KiB to 5.27 KiB in TorchScript or 2.55 KiB in ONNX.
- Palette: Single-root sequential blue; exact values are directly labeled and retained in the source inventory.
- Source: `report_support/file_inventory.json`.

Both charts use a zero baseline because they compare absolute magnitude. The report table is retained for exact lookup and audit detail.
