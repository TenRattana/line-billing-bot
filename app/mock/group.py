from pathlib import Path

from app.mock.jsontotxt import export_group_txt


INPUT_FILE = Path(
    "/data/validated/output/group_latest.json"
)

OUTPUT_FILE = (
    Path(__file__).resolve().parent
    / "group.txt"
)


def build() -> None:
    export_group_txt(
        INPUT_FILE,
        OUTPUT_FILE,
    )


if __name__ == "__main__":
    build()
