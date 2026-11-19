"""Extract single days from the remote 7z archive using HTTP range reads (no full download)."""
import sys, fsspec, py7zr
URL = "https://pub-091bd9e794bb4877b10b29e6df80f065.r2.dev/2026-10/delhi-dtc-bus-gtfs-rt-2026-10.7z"
days = sys.argv[1:]
f = fsspec.open(URL, "rb", block_size=16 * 2**20).open()
z = py7zr.SevenZipFile(f)
targets = [f"bus_movements_{d.replace('-', '_')}.db" for d in days]
z.extract(path="data/gps", targets=targets)
print("done", targets)
