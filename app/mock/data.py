from pathlib import Path

from app.mock.jsontotxt import export_data_txt


INPUT_FILE = Path(
    "/data/validated/output/ar_outstanding_latest.json"
)

OUTPUT_FILE = (
    Path(__file__).resolve().parent
    / "data.txt"
)


def build() -> None:
    export_data_txt(
        INPUT_FILE,
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    build()
