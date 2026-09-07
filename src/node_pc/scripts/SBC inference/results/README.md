# Development-host benchmark

These are model-only measurements on the development machine, not the ROCK 5A.
Input resolution was 600x400, with 20 warm-up runs and 100 measured runs. CPU affinity
was OS-managed. Use `benchmark.py` on the ROCK 5A for the real deployment result.

| Threads | Backend | Median ms | FPS | Speedup vs eager |
|---:|---|---:|---:|---:|
| 1 | Original eager PyTorch | 8.262 | 121.0 | 1.00x |
| 1 | Fused/frozen TorchScript | 3.237 | 308.9 | 2.55x |
| 1 | ONNX Runtime | 6.773 | 147.7 | 1.22x |
| 2 | Original eager PyTorch | 4.426 | 225.9 | 1.00x |
| 2 | Fused/frozen TorchScript | 1.836 | 544.7 | 2.41x |
| 2 | ONNX Runtime | 4.107 | 243.5 | 1.08x |
| 4 | Original eager PyTorch | 2.510 | 398.4 | 1.00x |
| 4 | Fused/frozen TorchScript | 1.072 | 933.3 | 2.34x |
| 4 | ONNX Runtime | 2.934 | 340.9 | 0.86x |

At four threads, original-vs-TorchScript maximum floating-point error was
`4.17e-7` and mean error was `3.91e-8`. After conversion to 8-bit PNG, only 5 of
240,000 pixels differed, each by one value in one color channel. The images are
visually identical.
