"""Smoke check: file attachment + MIME detection without API calls."""
import tempfile
from pathlib import Path

from aamp.chat import detect_mime, load_attachment, GEMINI_SUPPORTED_MIMES


def main() -> None:
    print("=== MIME detection ===")
    cases = [
        ("foo.pdf", "application/pdf"),
        ("foo.csv", "text/csv"),
        ("foo.md", "text/markdown"),
        ("foo.txt", "text/plain"),
        ("foo.png", "image/png"),
        ("foo.json", "application/json"),
        ("foo.xyz", "application/octet-stream"),  # unknown
    ]
    for name, expected in cases:
        got = detect_mime(Path(name))
        marker = "OK" if got == expected else f"!! expected {expected}"
        supported = "[Gemini]" if got in GEMINI_SUPPORTED_MIMES else "[unknown]"
        print(f"  {name:12} -> {got:35} [{supported}] {marker}")

    print("\n=== load_attachment ===")
    with tempfile.TemporaryDirectory() as td:
        # Create a CSV
        csv_path = Path(td) / "schedule.csv"
        csv_path.write_text("period,start,end\n1,08:00,08:55\n2,09:00,09:55\n", encoding="utf-8")
        part, info = load_attachment(csv_path)
        print(f"  CSV file: {info['name']} {info['size_bytes']} bytes, mime={info['mime']}, "
              f"gemini_supported={info['gemini_supported']}")
        assert info["mime"] == "text/csv"
        assert info["gemini_supported"]
        assert part is not None

        # Create a binary blob with unknown extension
        bin_path = Path(td) / "weird.xyz"
        bin_path.write_bytes(b"\x00\x01\x02\x03" * 100)
        part, info = load_attachment(bin_path)
        print(f"  Unknown ext: {info['name']} mime={info['mime']}, gemini_supported={info['gemini_supported']}")
        assert info["mime"] == "application/octet-stream"
        assert not info["gemini_supported"]

        # Missing file
        try:
            load_attachment(Path(td) / "does_not_exist.pdf")
            assert False, "should have raised"
        except FileNotFoundError as e:
            print(f"  missing file correctly raised: {e}")

    print("\nAll smoke checks passed.")


if __name__ == "__main__":
    main()
